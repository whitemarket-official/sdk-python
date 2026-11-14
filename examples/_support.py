"""Helpers shared by the scripts in `examples/` (not an example itself).

Every script reads the Partner Token with `WhiteMarketClient.from_env()` (the `WHITEMARKET_PARTNER_TOKEN`
environment variable) and never prints it. A failure no script handles ends it with `failure_report`: the
class, HTTP status, and for a GraphQL error each error's category, path and server message, never a bare
traceback.
"""

import argparse
import re
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation

from whitemarket import LiveTransport, WhiteMarketClient
from whitemarket.deals import DealPredicate
from whitemarket.errors import (
    GraphQLError,
    HttpError,
    NotFoundError,
    PurchaseOutcomeUnknownError,
    WhiteMarketError,
)
from whitemarket.live import LiveEvent, ProductAdded, ProductEdited, ProductRemoved
from whitemarket.models import BuyResult, DealState

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
EXIT_REJECTED = 1
EXIT_USAGE = 2
EXIT_OUTCOME_UNKNOWN = 3
STATUS_POLL_SECONDS = 30.0  # a trade can take hours: one cheap query every 30 s


def out(text: str = "") -> None:
    sys.stdout.write(f"{text}\n")


def warn(text: str) -> None:
    sys.stderr.write(f"{text}\n")


def printable(text: str) -> str:
    """Server text with every control character replaced, so it cannot drive the terminal."""
    return _CONTROL.sub("?", text)


def failure_report(error: BaseException) -> str:
    """A failure as text: every exception of the chain with its class, HTTP status, message and, for a
    GraphQL error, each error's category, path and server message. Branch on the category in code, never
    on this text."""
    lines: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    depth = 0
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        pad = "  " * depth
        status = f" (HTTP {current.status})" if isinstance(current, HttpError) else ""
        prefix = "" if depth == 0 else f"{pad}caused by "
        lines.append(f"{prefix}{type(current).__name__}{status}: {printable(str(current))}")
        if isinstance(current, GraphQLError):
            for entry in current.errors:
                where = ".".join(str(part) for part in entry.path) or "(no path)"
                category = entry.category or "no category"
                lines.append(f"{pad}  - [{category}] at {where}: {printable(entry.message)}")
        if isinstance(current, PurchaseOutcomeUnknownError) and current.last_lookup_error:
            lookup = current.last_lookup_error
            lines.append(f"{pad}  last lookup: {type(lookup).__name__}: {printable(str(lookup))}")
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
        depth += 1
    return "\n".join(lines)


def run(main: Callable[[Sequence[str] | None], int]) -> None:
    """Run `main` as the script body: exit with its code; a failure prints `failure_report`, exit 1."""
    try:
        code = main(None)
    except KeyboardInterrupt:
        code = 130
    except Exception as error:  # the last line of a script: report, never a bare trace
        warn(failure_report(error))
        code = 1
    raise SystemExit(code)


def make_parser(doc: str | None) -> argparse.ArgumentParser:
    """A parser whose help is the module docstring of the example."""
    return argparse.ArgumentParser(
        description=doc, formatter_class=argparse.RawDescriptionHelpFormatter
    )


def price_argument(text: str) -> Decimal:
    """argparse type: a positive decimal such as `5.00`. Money is never a float."""
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a decimal number: {text!r}") from None
    if not (value.is_finite() and value > 0):
        raise argparse.ArgumentTypeError("the price must be a positive number")
    return value


def new_custom_id() -> str:
    """1 to 100 characters. Reuse the SAME id to retry the SAME purchase, never a new one."""
    return f"example-{uuid.uuid4().hex[:16]}"


def print_status_changes(until: DealPredicate) -> DealPredicate:
    """Wrap a `wait_for` condition: print the status with a time whenever it differs from the previous
    poll, then return the verdict of `until` unchanged."""
    out("waiting...")
    previous: list[str] = []

    def check(state: DealState) -> bool:
        status = state.status.value
        if not previous or previous[-1] != status:
            out(f"{time.strftime('%Y-%m-%d %H:%M:%S')} status {status}")
            previous[:] = [status]
        return until(state)

    return check


def buy_guarded(client: WhiteMarketClient, custom_id: str, buy: Callable[[], BuyResult]) -> int:
    """Run a purchase and print its outcome. The caller has already persisted `custom_id`.

    A rejection (a GraphQL error before the purchase ran) means nothing was bought. An unknown outcome
    means neither success nor rejection is proven: never buy again with a new id, look the deal up by
    the old one.
    """
    try:
        result = buy()
    except PurchaseOutcomeUnknownError as error:
        warn(f"Outcome unknown for custom_id {error.custom_id}. Do NOT buy again; check it later:")
        warn(f"  python examples/track_deal_polling.py {error.custom_id}")
        warn(failure_report(error))
        try:
            out(f"The deal exists after all: {client.deals.get(error.custom_id).id}")
        except NotFoundError:
            warn("No deal with this custom_id yet.")
        except WhiteMarketError as lookup:
            warn(f"Lookup failed: {failure_report(lookup)}")
        return EXIT_OUTCOME_UNKNOWN
    except GraphQLError as error:
        warn(f"Rejected, nothing was bought: {failure_report(error)}")
        return EXIT_REJECTED
    found = " (found by reconciliation)" if result.reconciled else ""
    out(f"Deal {result.deal.id} price {result.deal.price}{found}")
    return 0


def describe_product_event(event: LiveEvent) -> str:
    """One line per product event, public fields only."""
    if isinstance(event, ProductAdded):
        return f"added   {event.id} {event.market_hash_name} {event.price}"
    if isinstance(event, ProductEdited):
        return f"edited  {event.id} price={event.price}"
    if isinstance(event, ProductRemoved):
        return f"removed {event.id} {event.market_hash_name}"
    return f"other   {type(event).__name__} on {event.channel}"


def print_product_feed(transport: LiveTransport, wanted: int, time_limit: float) -> int:
    """Print `wanted` live product events, then stop; exit code 1 when fewer arrive in `time_limit` s."""
    seen = 0
    deadline = time.monotonic() + time_limit
    with WhiteMarketClient.from_env() as client, client.live(transport) as live:
        live.on_connected(lambda reconnected: out(f"connected (reconnected={reconnected})"))
        live.on_error(lambda error: out(f"non-fatal problem: {type(error).__name__}"))
        live.subscribe_products()
        while seen < wanted and time.monotonic() < deadline:
            event = live.poll(5.0)
            if event is not None:
                seen += 1
                out(f"{seen}: {describe_product_event(event)}")
    if seen < wanted:
        warn(f"only {seen} of {wanted} events arrived")
        return 1
    return 0
