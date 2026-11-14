"""Use the generated layer directly: a typed operation (`market_list`) and a hand-written document (`execute`).

    WHITEMARKET_PARTNER_TOKEN=... python examples/raw_generated_operation.py

Read-only: both documents are queries. A document that is not clearly a query is treated as a
mutation and is never retried. `client.generated` runs on the client's own token, retry policy and
error mapping. Its names follow the schema (`market_list`, `forward_pagination`), not the high-level
API; the typed inputs live in `whitemarket._generated`.
"""

from collections.abc import Sequence

from _support import make_parser, out, run
from whitemarket import WhiteMarketClient
from whitemarket._generated.input_types import ForwardPaginationInput


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    with WhiteMarketClient.from_env() as client:
        generated = client.generated
        # 1. A typed operation: schema field name, typed input, typed result.
        listing = generated.market_list(forward_pagination=ForwardPaginationInput(first=3))
        for edge in listing.market_list.edges or []:
            out(edge.node.id if edge and edge.node else "no node")
        # 2. A raw document: variables are JSON-ready values; the answer is the raw `data` dict.
        data = generated.execute("query Ping { test_ping }")
        out(f"test_ping: {data.get('test_ping')!r}")
    return 0


if __name__ == "__main__":
    run(main)
