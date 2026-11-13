# Parametrize, fixtures and exceptions (pytest)

Recalled for pytest 8.x. Check the docs of the pinned version before using anything not listed here: https://docs.pytest.org/en/stable/

## `@pytest.mark.parametrize`

```python
@pytest.mark.parametrize(
    ("comment", "valid"),
    [
        pytest.param("x" * 255, True, id="255 chars -> accepted"),
        pytest.param("x" * 256, False, id="256 chars -> rejected"),
        pytest.param("", True, id="empty -> accepted"),
    ],
)
def test_comment_length_limit(comment: str, valid: bool) -> None: ...
```

- Argument names as a tuple of strings (or one comma-separated string).
- `pytest.param(*values, id="...", marks=...)` gives each case a readable id; ids appear in failure output and in `-k` selection (`make test K="256 chars"`).
- Alternative: `ids=[...]` list or `ids=callable` on the decorator. Prefer `pytest.param` so the id sits next to its data.
- Stacked `parametrize` decorators produce the cartesian product: use it for "every case x both clients", not by accident.
- `marks=pytest.mark.xfail(strict=True, reason="... #<issue>")` for a known bug pinned by a test; a non-strict xfail that passes silently is a hidden green.
- Keep case data plain (numbers, strings, small tuples). Build clients and fakes in fixtures, not in the case list: case lists are evaluated at collection time.

## Fixtures

```python
@pytest.fixture
def token_store() -> InMemoryTokenStore:
    return InMemoryTokenStore()


@pytest.fixture
async def async_client(token_store):        # async fixture: needs pytest-asyncio
    async with AsyncWhiteMarketClient(partner_token="test-partner-token", token_store=token_store) as client:
        yield client
```

- `yield` fixtures run teardown after the test: the place to close clients.
- Default scope is `function`; wider scopes (`module`, `session`) only for immutable, expensive data (parsed fixture files), never for clients or anything with state.
- Built-in fixtures worth knowing: `tmp_path` (per-test `pathlib.Path`), `monkeypatch` (`setenv`, `setattr` on **external** objects only), `caplog` (log records; `caplog.set_level(logging.DEBUG, logger="whitemarket")`), `capsys`.
- Fixture parametrization (`@pytest.fixture(params=[...])`) is the clean way to run a test against both the async and the sync client.

## Exceptions

```python
with pytest.raises(PurchaseOutcomeUnknownError) as excinfo:
    client.buying.buy_product(product_id, price=Decimal("1.00"), custom_id=custom_id)

assert excinfo.value.custom_id == custom_id
```

- Keep only the act inside the `with` block.
- `match=` is a regex searched in `str(exc)`; use it for messages the SDK owns, never to branch on server `message` text (CLAUDE.md rule 4).
- Async: `with pytest.raises(...)` works around `await ...` inside an async test.

## Warnings

- `pytest.warns(DeprecationWarning, match=...)` for deprecated public names (CLAUDE.md rule 16).
- With `filterwarnings = ["error"]` in the config, an unexpected warning fails the test; that is intended.

## Selecting and debugging

- `make test K="<expr>"`: `-k` matches test names and parametrize ids (`and`, `or`, `not` allowed).
- On failure read the assertion diff pytest prints (assert rewriting); add `-vv` via `VERBOSE=1` only when the diff is truncated.
