"""Base class of the generated client: the SDK's own executor-backed GraphQL base.

ariadne-codegen copies this file into `_generated/async_base_client.py`; it must hold the text
`class AsyncBaseClient`. The base itself lives in `src/whitemarket/_async/graphql_base.py`.
"""

from whitemarket._async.graphql_base import AsyncGraphQLBase


class AsyncBaseClient(AsyncGraphQLBase):
    """Generated operations call `execute` and `_decode`; the executor owns the IO."""
