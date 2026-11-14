"""The live smoke runner: read-only queries, one export file, SSE and WebSocket (SDK_SPEC 6.4).

Exit codes: 0 all steps passed, 1 a step failed, 2 no usable token or the report cannot be written.
The only mutation that can happen is the SDK's own `auth_token` exchange inside the token provider.
"""

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from live_smoke import catalog, report
from live_smoke.classify import classify
from live_smoke.env import partner_token
from live_smoke.guard import ReadOnlyExecutor
from live_smoke.report import Status, StepResult
from whitemarket import LiveTransport, WhiteMarketClient
from whitemarket._generated.sync_client import GeneratedClient
from whitemarket._sync.client import ENV_BASE_URL
from whitemarket.exports import ExportKind
from whitemarket.live import ProductAdded, ProductEdited, ProductRemoved

EXPORT_ROWS = 100
LIVE_TIMEOUT_SECONDS = 120.0
POLL_SECONDS = 5.0
REPORT_FILE = Path(__file__).resolve().parents[2] / "var" / "live-smoke" / "report.md"


class TooFewExportRowsError(Exception):
    """The export stream ended before the wanted number of rows."""


class NoProductsUpdateError(Exception):
    """No products event arrived within the time limit."""


def run_step(name: str, step: Callable[[], Any]) -> StepResult:
    """Time a step and turn its outcome into a result; the exception class is all that is kept."""
    started = time.monotonic()
    try:
        step()
    except Exception as error:  # a failing step is a result, not a crash of the smoke
        return classify(name, error, _elapsed_ms(started))
    return StepResult(name, Status.PASSED, _elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _export_rows(client: WhiteMarketClient) -> None:
    rows = client.exports.stream_products()
    try:
        for count, _ in enumerate(rows, start=1):
            if count >= EXPORT_ROWS:
                return
    finally:
        rows.close()
    raise TooFewExportRowsError


def _live_event(client: WhiteMarketClient, transport: LiveTransport) -> None:
    deadline = time.monotonic() + LIVE_TIMEOUT_SECONDS
    with client.live(transport) as live:
        live.subscribe_products()
        while (left := deadline - time.monotonic()) > 0:
            event = live.poll(min(POLL_SECONDS, left))
            if isinstance(event, ProductAdded | ProductEdited | ProductRemoved):
                return
    raise NoProductsUpdateError


def run_all(client: WhiteMarketClient) -> list[StepResult]:
    # The guard sits between the smoke's generated client and the SDK's executor.
    api = GeneratedClient(ReadOnlyExecutor(client.generated._executor))
    results = [run_step(f"query {name}", call) for name, call in catalog.steps(api).items()]
    results.append(
        run_step("export products meta", lambda: client.exports.meta(ExportKind.PRODUCTS))
    )
    results.append(
        run_step(f"export products first {EXPORT_ROWS} rows", lambda: _export_rows(client))
    )
    for transport in (LiveTransport.WS, LiveTransport.SSE):
        results.append(
            run_step(
                f"live {transport.value} products update",
                lambda t=transport: _live_event(client, t),
            )
        )
    return results


def main() -> int:
    token = partner_token()
    if token is None:
        sys.stderr.write("live-smoke: WHITEMARKET_PARTNER_TOKEN is not set.\n")
        return 2
    try:
        client = WhiteMarketClient(
            partner_token=token, base_url=os.environ.get(ENV_BASE_URL) or None
        )
    except ValueError:
        sys.stderr.write("live-smoke: WHITEMARKET_PARTNER_TOKEN is not a usable header value.\n")
        return 2
    with client:
        results = run_all(client)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report.render(results), encoding="utf-8")
    sys.stdout.write(f"live-smoke: {report.summary(results)}\n")
    for result in results:
        if result.status is Status.FAILED:
            sys.stdout.write(f"  FAIL {result.name}: {result.exception_class} {result.category}\n")
    return report.exit_code(results)
