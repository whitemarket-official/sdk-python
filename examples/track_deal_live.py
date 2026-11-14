"""Wait for a deal to reach the exchanged or completed state, woken early by the personal live channel.

    WHITEMARKET_PARTNER_TOKEN=... python examples/track_deal_live.py <deal id or custom_id> [--timeout SECONDS]

Read-only: it only watches the deal. By default it waits without a timeout (a trade can take hours),
polls every 30 seconds at most and prints every status change. A deal event is a hint: `wait_for`
then reads the authoritative state. Without `live=` the same call only polls. The counterparty's
Steam id on deal events is personal data and is not printed.
"""

from collections.abc import Sequence

from _support import STATUS_POLL_SECONDS, make_parser, out, print_status_changes, run, warn
from whitemarket import WhiteMarketClient
from whitemarket.deals import Until
from whitemarket.errors import DealWaitTimeoutError, LiveConnectionError
from whitemarket.live import DealEvent


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument("deal", help="deal id or custom_id")
    parser.add_argument("--timeout", type=float, default=None, help="seconds; default: no limit")
    args = parser.parse_args(argv)
    with WhiteMarketClient.from_env() as client, client.live() as live:
        # After a reconnect the events of the gap are lost; wait_for still polls on its interval.
        live.on_connected(lambda reconnected: out("reconnected" if reconnected else "connected"))
        live.on(
            DealEvent,
            lambda event: out(f"deal event {type(event).__name__} for deal {event.deal_id}"),
        )
        live.subscribe_personal()
        try:
            state = client.deals.wait_for(
                args.deal,
                print_status_changes(Until.exchanged_or_completed()),
                timeout=args.timeout,
                poll_interval=STATUS_POLL_SECONDS,
                live=live,
            )
        except DealWaitTimeoutError:
            warn("Timed out; the deal did not reach the state in time.")
            return 1
        except LiveConnectionError as error:
            warn(f"Live connection ended: close code {error.code}")
            return 1
    out(f"Deal reached {state.status.value}")
    return 0


if __name__ == "__main__":
    run(main)
