"""The scripts in `examples/`: all compile and import, the read-only ones run against an HTTP fake,
the money-moving ones send nothing without `--yes`, and the failure text is terminal-safe."""

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from support import market_payloads as mp
from support.clients import ACCESS
from support.http import data
from whitemarket import WhiteMarketClient
from whitemarket.errors import GraphQLError, HttpError, PurchaseOutcomeUnknownError

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
# SDK_SPEC 9 plus `buy_product_by_id` (docs/SPEC_SYNC.md item 5).
EXPECTED = {
    "auth_and_ping",
    "search_market",
    "iterate_all_listings",
    "buy_cheapest_by_name",
    "buy_product_by_id",
    "track_deal_polling",
    "track_deal_live",
    "sell_semi",
    "sell_manual",
    "export_prices_lookup",
    "export_products_stream",
    "sse_products_feed",
    "ws_products_feed",
    "ws_personal_deals",
    "raw_generated_operation",
}


@pytest.fixture(autouse=True)
def _examples_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLES))


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_client(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Make `WhiteMarketClient.from_env()` build a client on a mock transport."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def from_env(cls: type[WhiteMarketClient], **_: Any) -> WhiteMarketClient:
        http = httpx.Client(transport=httpx.MockTransport(answer))
        return cls(access_token=ACCESS, http_client=http)

    monkeypatch.setattr(WhiteMarketClient, "from_env", classmethod(from_env))
    return seen


def graphql_answer(request: httpx.Request) -> httpx.Response:
    query = json.loads(request.content)["query"]
    if "test_ping" in query:
        return data(test_ping="pong").build()
    if "market_list" in query:
        return data(**mp.market_list_data(["slug-a", "slug-b"], "c2", True)).build()
    raise AssertionError(f"unexpected document: {query[:60]}")


def no_request(_: httpx.Request) -> httpx.Response:
    raise AssertionError("a dry run must not send a request")


def test_the_example_set_is_the_documented_one() -> None:
    found = {p.stem for p in EXAMPLES.glob("*.py") if not p.name.startswith("_")}
    assert found == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_example_compiles_and_exposes_main(name: str) -> None:
    path = EXAMPLES / f"{name}.py"
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    assert callable(load(name).main)


def test_auth_and_ping_runs_against_the_fake_and_never_prints_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_client(monkeypatch, graphql_answer)

    assert load("auth_and_ping").main([]) == 0

    shown = capsys.readouterr().out
    assert "test_ping answered: pong" in shown
    assert "Access token obtained: ***" in shown
    assert ACCESS not in shown


def test_search_market_prints_the_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = fake_client(monkeypatch, graphql_answer)

    assert load("search_market").main([]) == 0

    shown = capsys.readouterr().out
    assert "id-slug-a" in shown
    assert "id-slug-b" in shown
    assert "More pages: yes" in shown
    assert json.loads(seen[0].content)["variables"]["forwardPagination"] == {"first": 10}


def test_iterate_all_listings_stops_at_the_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = fake_client(monkeypatch, graphql_answer)

    assert load("iterate_all_listings").main(["--limit", "1"]) == 0

    assert "Listed 1 listings" in capsys.readouterr().out
    assert len(seen) == 1  # the second page of a has_next_page answer was never requested


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        pytest.param(
            "buy_cheapest_by_name", ["AK-47 | Redline", "5.00"], id="buy_cheapest_by_name"
        ),
        pytest.param("sell_semi", ["1234", "5.00"], id="sell_semi"),
        pytest.param("sell_manual", ["list", "1234", "5.00"], id="sell_manual list"),
        pytest.param("sell_manual", ["report", "deal-1", "offer-1"], id="sell_manual report"),
    ],
)
def test_money_moving_examples_do_a_dry_run_without_yes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    argv: list[str],
) -> None:
    seen = fake_client(monkeypatch, no_request)

    assert load(name).main(argv) == 0

    assert "Nothing was done. Add --yes" in capsys.readouterr().out
    assert seen == []


def test_a_price_that_is_not_a_positive_decimal_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stop:
        load("buy_cheapest_by_name").main(["AK-47 | Redline", "-1"])

    assert stop.value.code == 2
    assert "positive" in capsys.readouterr().err


def test_failure_report_names_class_status_category_and_path_and_cleans_control_characters() -> (
    None
):
    support = load("_support")
    graphql = GraphQLError.from_payload(
        [
            {
                "message": "bad\x1b[31m thing\n",
                "path": ["market_buy", 0],
                "extensions": {"category": "market.product.not_found"},
            },
            {"message": "second"},
        ]
    )
    outcome = PurchaseOutcomeUnknownError("cid-1", HttpError(503))
    outcome.__cause__ = graphql

    report = support.failure_report(outcome)

    assert "PurchaseOutcomeUnknownError" in report
    assert "caused by NotFoundError" not in report  # a mixed answer is a plain GraphQLError
    assert "caused by GraphQLError" in report
    assert "- [market.product.not_found] at market_buy.0: bad?[31m thing?" in report
    assert "- [no category] at (no path): second" in report
    assert "last lookup: HttpError: HTTP 503" in report
    assert "\x1b" not in report
    assert "\n\n" not in report


def test_failure_report_shows_the_http_status() -> None:
    assert "HttpError (HTTP 418): HTTP 418" in load("_support").failure_report(HttpError(418))
