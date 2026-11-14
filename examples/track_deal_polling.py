"""Wait for a deal to reach the exchanged or completed state by polling.

    WHITEMARKET_PARTNER_TOKEN=... python examples/track_deal_polling.py <deal id or custom_id> [--timeout SECONDS]

Read-only: it only watches the deal. By default it waits without a timeout (a trade can take hours:
Steam trade holds, a seller who is away), polls every 30 seconds and prints every status change. To
wake up on live events instead of waiting, see `examples/track_deal_live.py`.
"""

from collections.abc import Sequence

from _support import STATUS_POLL_SECONDS, make_parser, out, print_status_changes, run, warn
from whitemarket import WhiteMarketClient
from whitemarket.deals import Until
from whitemarket.errors import DealWaitTimeoutError


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument("deal", help="deal id or custom_id")
    parser.add_argument("--timeout", type=float, default=None, help="seconds; default: no limit")
    args = parser.parse_args(argv)
    with WhiteMarketClient.from_env() as client:
        try:
            state = client.deals.wait_for(
                args.deal,
                print_status_changes(Until.exchanged_or_completed()),
                timeout=args.timeout,
                poll_interval=STATUS_POLL_SECONDS,
            )
        except DealWaitTimeoutError:
            warn("Timed out; the deal did not reach the state in time.")
            return 1
    out(f"Deal reached {state.status.value}")
    return 0


if __name__ == "__main__":
    run(main)
