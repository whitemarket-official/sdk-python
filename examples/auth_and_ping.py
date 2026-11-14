"""Exchange the Partner Token for an access token and check the connection with `test_ping`.

    WHITEMARKET_PARTNER_TOKEN=... python examples/auth_and_ping.py

Read-only: no order, purchase or listing is made. The token is used, never printed: a `Secret`
prints as `***`.
"""

from collections.abc import Sequence

from _support import make_parser, out, run
from whitemarket import WhiteMarketClient


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    with WhiteMarketClient.from_env() as client:
        out(f"Access token obtained: {client.auth.access_token()}")
        out(f"test_ping answered: {client.auth.ping()}")
    return 0


if __name__ == "__main__":
    run(main)
