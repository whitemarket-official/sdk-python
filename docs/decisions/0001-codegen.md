# 0001. Code generation of the Python generated layer

- Status: accepted 2026-11-13 (default tool of CLAUDE.md "Codegen"; owner instruction: take the default and record open questions)
- Date: 2026-11-13
- Spike: task T1.3, run on the real `schema/partner.graphql`, the 69 documents of `graphql/operations/**` and the 28
  fragments of `graphql/fragments/**` (unchanged copies), Python 3.13.3, macOS.

## Context

SDK_SPEC 1.1 requires a generated layer: every input and enum type of the schema, one typed method per operation, a raw
`execute`, enums with an unknown fallback, deprecated input fields marked, generated code committed with a "DO NOT EDIT"
header and checked by `make codegen-check`. CLAUDE.md adds:

- rule 1: generated code is never edited by hand; selection changes go through `graphql/overrides/`;
- rule 2 and SDK_SPEC 1.4: the transport must know whether a request is a query or a mutation (mutations are never retried);
- rule 3 and SDK_SPEC 4: no binary float anywhere; 64-bit ids never lose precision;
- rule 5: unknown enum values and unknown `__typename` values decode, never crash (SPEC_SYNC 2026-11-02 item 2:
  `market_list` with an unknown `__typename` at the depth limit must decode);
- SDK_SPEC 8: credential fields of responses decode into the secret type, also in the generated layer;
- language rules: async core, sync variant produced by an unasync-style token rewrite (decided by the main session, as in
  httpcore); our transport owns HTTP, auth, retry and errors; generated code passes `mypy --strict` and pyright strict;
  `ariadne-codegen` must not be a runtime dependency.

The operation documents are fixed (byte-identical across the 7 SDKs, SDK_SPEC 1.2); the Python codegen consumes them as
they are.

Schema facts that drive the design [schema `schema/partner.graphql`]:

| Fact | Where | Consequence |
|---|---|---|
| Custom scalars: `Uuid`, `DateTime`, `FileUpload` | lines 910, 956, 3065 | `Uuid` -> `str`, `DateTime` -> aware `datetime`, `FileUpload` input field dropped |
| Money is `Money { value: String!, currency: Currency! }` | WHITEMARKET_API 4 | already exact; stays `str` in the generated layer, `Decimal` in the high-level mappers |
| Wear is `float: String` (`CSGOInventoryItem.float`, `csgoFloatFrom/To: String`) | lines 203, 1123-1126 | already exact (`str`) |
| Binary `Float` fields: `CSGOInventoryItem.fade: Float` (output), `csgoFadeFrom/To: Float` on two search inputs | lines 195, 1976, 1985, 2727, 2736 | must become `Decimal` (see below) |
| 64-bit ids `assetId`, `classId`, `instanceId` are `String!` | e.g. lines 168, 180, 209 | `str`, no precision issue; `Int` fields decode to Python `int` (arbitrary precision) |
| Abstract types: interfaces `InventoryItemInterface`, `MarketOrder`, `MarketOrderPublic`, `SteamItemInterface`; unions `AchievementParamUnion`, `MarketProductUnion` | lines 21, 995, 1554, 1643, 2159, 2999 | decode by `__typename` with an unknown fallback |
| Credential-named string fields: `AuthTokens.accessToken`, `WalletDeposit.airwallexSecret` (all others matching the SDK_SPEC 8 markers are `Boolean`/`Int` or root fields) | lines 63, 3087 | `Secret` |

## Options

### 1. ariadne-codegen 0.19.0 (default in CLAUDE.md) with one project plugin

Latest release 0.19.0, uploaded 2026-08-28 [PyPI JSON]; requires Python >= 3.10, `graphql-core>=3.2.7,<3.3`,
`pydantic>=2.8,<3`, `httpx~=0.28`, `ruff>=0.15,<0.16`, `click`, `toml` [PyPI JSON `requires_dist`]. Results of the spike:

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | All 69 operations + 28 fragments unchanged, fragments spread across files | **pass** | `queries_path` pointing at a directory reads every `*.graphql` recursively, sorted by path [code `ariadne_codegen/schema.py:288-303`]; run exit 0, 69 methods (33 `query`, 36 `mutation`), one module per operation [observed]. The directory must hold only `operations/**` and `fragments/**`: `graphql/overrides/` would duplicate operation names, so `make codegen` stages the two directories (see Decision). Documents are re-printed by graphql-core (comments of override files are dropped, semantics unchanged) |
| 2 | Sync and async | **pass** | `async_client` generates one flavour per run [docs configuration, async-vs-sync]. Decision: generate the async client only and derive `sync_client.py` with the same unasync rewrite as the hand-written code (one generator run, models shared). Spike: the rewritten sync client passes mypy/pyright strict and a call test [observed] |
| 3 | Custom base client, our transport, operation type | **pass with plugin** | `base_client_name` / `base_client_file_path` / `base_client_module_name`; the base must provide `execute(query, operation_name, variables, **kwargs)` and `get_data(response)` [docs configuration "Base Client customization"]. The file is copied into the package and must contain the text `class <base_client_name>` [code `settings.py:586-589`], so it is a 7-line shim subclassing the hand-written executor. The operation type is not passed by default; the plugin hook `generate_client_method` receives the `OperationDefinitionNode` [docs hooks] and rewrites each call to `self.execute(..., operation_type="query"\|"mutation")`, also removing the `**kwargs` pass-through from the public methods. Test: `market_list` arrives as `query`, `market_lifetime_all` as `mutation` [observed] |
| 4 | Scalars, money, floats | **pass with plugin** | `[tool.ariadne-codegen.scalars.<Name>] type/parse/serialize` [docs custom scalars]: `Uuid` -> `str`, `DateTime` -> `pydantic.AwareDatetime` (naive values are rejected). The built-in `Float` cannot be remapped through config (`SIMPLE_TYPE_MAP` is consulted before custom scalars) [code `client_generators/constants.py:4-10`, `result_fields.py:185-191`]; the plugin renames `float` -> `Decimal` in `generate_result_field` and `generate_input_field`. A `Decimal` field fed from `json.loads(text)` would still pass through a binary float, so the transport decodes with `json.loads(body, parse_float=Decimal)` (ints stay exact Python ints) and encodes variables with an own encoder that writes `Decimal` as a JSON number literal and refuses `float`. Test: `"fade": 95.130000000000000001` decodes to exactly `Decimal("95.130000000000000001")`; `csgoFadeFrom=Decimal("95.130000000000000001")` is sent as that literal [observed] |
| 5 | 64-bit ids | **pass** | `String!` in the schema -> `str` [observed `asset_id`, `class_id`, `instance_id` annotations] |
| 6 | Unknown enum values | **pass with plugin** | Stock output is `class X(str, Enum)` [observed]; pydantic rejects unknown values. Plugin hook `generate_enum` sets the base to the hand-written `UnknownTolerantEnum(str, Enum)` whose `_missing_` returns a pseudo-member named `UNKNOWN` that keeps the raw value (`is_unknown`, `.value == "TELEPORT"`, not in `list(Enum)`); pydantic calls `_missing_` [observed pydantic 2.14.3]. Non-string values still fail |
| 7 | Interfaces/unions, unknown `__typename` at depth | **pass with plugin** | Stock output is a pydantic discriminated union over `Literal` `typename__` fields (`Field(discriminator="typename__")`) [code `result_fields.py:367-398`], which rejects any new type, and the depth-limit selection `__typename id` is typed `Literal["CSGOInventoryItem","InventoryItemInterface"]` [observed]. Plugin (`generate_result_types_module`, `generate_fragments_module`): every `typename__` `Literal` that names an abstract type becomes `str`; every union becomes `Annotated[Union[Annotated[A, Tag("A")], ..., Annotated[Fallback, Tag("__unknown__")]], typename_discriminator("A", ...)]` (pydantic callable discriminator); the fallback is ariadne's own interface-named member, or a generated `<Prefix>UnknownTypename` model when every possible type is selected (`MarketProductUnion` in the `*_multiple` results); non-null union fields (`order_new`, `order_edit`) carry the discriminator on the field default and are normalised first. Tests: `market_list` with a known and an unknown `item.__typename`, and an unknown type at the depth limit (`product.item`), decode; `market_edit_multiple` with an unknown `product.__typename` decodes to the fallback [observed] |
| 8 | Credential fields -> secret type | **pass with plugin** | `generate_result_field` gets the `FieldNode`; a field whose name matches the SDK_SPEC 8 markers has `str` renamed to `Secret` (`AuthTokensFields.access_token` in `fragments.py`, `WalletDepositsWalletDeposits.airwallex_secret`). `Secret` validates through `__get_pydantic_core_schema__`; `repr`/`str` of the model do not contain the value [observed]. Found: a pydantic `ValidationError` for a **missing sibling** field prints the whole parent dict, token included [observed]; `hide_input_in_errors=True` hides it from `str()` but `errors()` still carries it [observed]. So the transport turns every `ValidationError` into `DecodeError` built from `errors(include_input=False, include_url=False, include_context=False)` and raises it `from None`, and the generated `BaseModel` sets `hide_input_in_errors=True` as defence in depth |
| 9 | Deprecated input fields, `FileUpload` | **pass with plugin** | Plugin adds `Field(deprecated=<reason>)` to deprecated input fields (pydantic emits `DeprecationWarning` on access, JSON schema marks them) [observed]; fields of scalar `FileUpload` (`PersonStoreInput.customAvatar`) are removed with their docstring, `encodedCustomAvatar` stays (PHP DEVIATIONS 1.1, ADR 0002 PHP). `multipart_uploads = false` drops the `Upload` class [docs configuration] |
| 10 | mypy `--strict` and pyright strict | **pass** | mypy 2.4.1 `--strict --python-version 3.11`: 0 errors in 88 files (generated + runtime stand-ins + a consumer file); pyright 1.1.414 strict: 0 errors [observed]. Without `use_alias_generator = true` both checkers reject constructing inputs by Python name (`MarketProductSearchInput(name_hash=...)`: "No parameter named", because pydantic's `dataclass_transform` makes `alias` the `__init__` parameter) [observed]; with it the alias moves to `alias_generator=to_camel` [docs configuration]. The plugin turns the remaining explicit input aliases (`from`, `type`, Python keywords) into `serialization_alias`, so `MoneyRangeInput(from_=...)` type-checks [observed] |
| 11 | Plugin API stability, runtime footprint | **acceptable, pinned** | Pre-1.0 policy: a minor release may break [docs versioning policy]; the plugin reads ariadne's AST shapes (forward references are emitted as `Name('"Cls"')`, `Literal` members likewise) [observed], so `ariadne-codegen==0.19.0` is pinned exactly and every bump is a reviewed PR guarded by the golden test and `make codegen-check`. Generated imports, all of them: `typing`, `decimal`, `pydantic` (+`pydantic.alias_generators`), relative imports, and `whitemarket._runtime.*` [observed grep]; no `httpx`, `websockets`, `graphql-core` or `ariadne_codegen` [docs generated-code dependencies + observed]. ariadne-codegen's own pins (`ruff<0.16`, `graphql-core<3.3`) conflict with the dev tools, so it lives in its own environment (`codegen` dependency group / `make install-codegen`) |

Other observations: output is deterministic (two runs, identical files) [observed]; ~25k lines in 78 files; importing the
whole generated package takes about 0.5 s on the host [observed], `defer_model_build` exists if that matters later
[docs configuration]. Models are per operation (`MarketListMarketListEdgesNode...`), with fragment classes shared as base
classes [docs fragments-and-forward-references] — the same shape as the PHP layer (PHP ADR 0002 "T3.1"), so high-level
mappers take structural types (Protocols) rather than one class per schema type.

### 2. Own generator over graphql-core (dev dependency only), as PHP did (`tools/codegen-php`)

Full control (no AST coupling to a third-party tool, exact output shape), but every construct ariadne already handles
(fragments as base classes, nested selections, inputs with defaults, naming, formatting) becomes our code and our tests.
PHP chose it because Sailor failed the runtime-footprint and per-instance-transport requirements (PHP ADR 0001); ariadne
fails neither: the footprint is pydantic only and the transport is injected per instance by construction.

## Decision

Option 1: **ariadne-codegen 0.19.0**, exact pin, dev-only and in its own environment, plus one project plugin
`tools/codegen/ariadne_plugin.py` (spike version 367 lines). A hand-written owner choice for option 2 is not needed; it
stays the fallback if a future ariadne release breaks the plugin beyond a reasonable fix.

Pipeline (`make codegen`):

1. `node tools/codegen/generate-operations.mjs` (shared, unchanged).
2. Stage the documents: copy `graphql/operations/{query,mutation}` and `graphql/fragments` into `var/codegen/documents/`
   (overrides are already merged into `graphql/operations/` by step 1 and must not be read twice).
3. `ariadne-codegen --config tools/codegen/ariadne.toml` with `PYTHONPATH=tools/codegen` -> `src/whitemarket/_generated/`.
4. `tools/unasync.py` (the same script that derives the hand-written sync code): `_generated/client.py` ->
   `_generated/sync_client.py`, `_generated/async_base_client.py` -> `_generated/base_client.py`.
5. `make codegen-check` repeats 2-4 into a temp dir and diffs.

Configuration (paths as in this repository; a separate TOML file keeps the dev `pyproject.toml` free of tool sections
that only the isolated environment reads, `--config` is documented [docs configuration]):

```toml
[tool.ariadne-codegen]
schema_path = "schema/partner.graphql"
queries_path = "var/codegen/documents"
target_package_name = "_generated"
target_package_path = "src/whitemarket"
client_name = "AsyncGeneratedClient"
client_file_name = "client"
base_client_name = "AsyncBaseClient"
base_client_file_path = "tools/codegen/async_base_client.py"   # 7-line shim, subclasses the hand-written executor
base_client_module_name = "async_base_client"
async_client = true
include_comments = "stable"            # replaced by the plugin's DO NOT EDIT header (get_file_comment)
convert_to_snake_case = true
include_all_inputs = true
include_all_enums = true
include_typename = true                # required: unions decode by __typename
multipart_uploads = false              # no Upload class; FileUpload is not sent (JSON transport)
show_deprecation_warnings = false      # deprecations are marked in code instead
use_alias_generator = true             # inputs construct by Python name under mypy/pyright
plugins = ["ariadne_plugin.WhiteMarketPlugin"]

[tool.ariadne-codegen.scalars.Uuid]
type = "str"

[tool.ariadne-codegen.scalars.DateTime]
type = "pydantic.AwareDatetime"
```

Plugin hooks [docs hooks] and what each does:

| Hook | Change |
|---|---|
| `get_file_comment` | `# DO NOT EDIT. Generated by ariadne-codegen ... Run make codegen.` on every file |
| `generate_enum`, `generate_enums_module` | base `UnknownTolerantEnum` (runtime), drop the `enum` import |
| `generate_result_field` | `float` -> `Decimal`; credential-named fields `str` -> `Secret` |
| `generate_result_types_module`, `generate_fragments_module` | `__typename` handling of point 7; imports of `Decimal`, `Secret`, `Tag`, `typename_discriminator` only when used (pyright `reportUnusedImport`) |
| `generate_input_field`, `generate_input_class`, `generate_inputs_module` | `float` -> `Decimal`; `alias` -> `serialization_alias`; `Field(deprecated=...)`; drop `FileUpload` fields |
| `generate_client_method`, `generate_client_module` | `operation_type="query"\|"mutation"` on `execute`, no `**kwargs` |
| `copy_code` | `base_model.py`: `UNSET`/`UnsetType` imported from the runtime (the transport drops them from variables); add `hide_input_in_errors=True` (not yet in the spike plugin) |

Hand-written runtime the generated code imports (module names are the implementer's choice; spike names in brackets):
the async GraphQL executor the shim subclasses (`execute(query, operation_name, variables, *, operation_type="mutation")`,
`get_data`; a raw `execute` without a declared type is a mutation and never retried, as in PHP `RawDocument`), the
`UnknownTolerantEnum` base, `Secret` (pydantic core schema; it must serialise as `***`, since nothing re-sends response models; the spike stand-in still serialises the value),
`typename_discriminator(*known)`, `UNSET`/`UnsetType`, and the JSON codec (`parse_float=Decimal`, own encoder).

Generated `Money.value` stays `str` (schema type, exact); the high-level mappers turn it into `Decimal` (SDK_SPEC 4).

Lint and types: ruff excludes `src/whitemarket/_generated/`; mypy `--strict` and pyright strict include it (the golden
test fails on any plugin change that emits code they reject).

## Consequences

- Runtime dependency of the generated layer: `pydantic` only. The floor must be `pydantic>=2.8` (`alias_generator` use
  per ariadne docs; callable discriminators and `Field(deprecated=...)` are older) — `pyproject.toml` currently says
  `pydantic>=2`; the lowest-dependency CI job checks the floor.
- The plugin is our code: golden test over a small fixture schema (one example per row of the hook table, executed:
  decode known/unknown enum and `__typename`, Decimal, Secret, input encoding), plus invariants over the real output (no
  `float` annotation, no `Field(discriminator=`, no `Literal` naming an abstract type, every credential-named string field
  is `Secret`).
- Upgrading ariadne-codegen is a deliberate PR (pre-1.0, minor = breaking); Dependabot ignores it or the PR runs
  `make codegen-check`.
- The transport owns the JSON codec and the `ValidationError` -> `DecodeError` mapping (finding of point 8).
- Per-operation models mean many classes per schema type; high-level mappers use Protocols (as PHP uses object shapes).

## Open questions (defaults applied)

1. Unknown enum representation: pseudo-member `UNKNOWN` of the same enum with the raw value (default) vs a separate
   `UnknownEnumValue` union type as in PHP. Default keeps signatures simple (`DeliveryType`, not `DeliveryType |
   UnknownEnumValue`); exhaustive `match` cannot force callers to handle it. Owner may prefer PHP parity.
2. Coupling to ariadne internals (AST shapes) is accepted with an exact pin; if a release breaks the plugin beyond a
   small fix, switch to option 2 (graphql-core generator). Default: stay on ariadne.
3. Deprecated **arguments** of operations (`market_buy(deliveryType)`) are not marked in the generated method signature
   (SDK_SPEC 1.1 asks only for input fields). Default: document in the high-level API only.

## Implementation notes (2026-11-13, T1.4 / T1.5)

What the production implementation does differently from the spike and the text above:

- Pipeline entry: `tools/codegen/generate.sh <out-root>` (stage documents, ariadne in `.venv-codegen`, unasync, ruff);
  `make codegen` runs it on `.`, `make codegen-check` on `var/codegen-check` and `diff -r`s operations, fragments,
  `_generated` and `_sync`. The config is `tools/codegen/ariadne.toml`; the script rewrites only `queries_path` and
  `target_package_path` for the scratch run. ariadne formats with `ruff --isolated`, so the output does not depend on
  where it runs.
- Runtime package `whitemarket._runtime` (private): `UnknownTolerantEnum` (a `StrEnum`), `typename_discriminator`,
  `json_codec` (`decode`, `to_plain`, `encode`), `Secret`, `UNSET`, `OperationType`, `decode_error_from`. The executor
  protocol and the generated-client base are IO code and live once in async form under `whitemarket._async`
  (`executor.py`: `AsyncOperationExecutor.execute(document, operation_name, variables, operation_type)`;
  `graphql_base.py`: `AsyncGraphQLBase`); `_sync` is derived by `tools/unasync.py`. The shim
  `tools/codegen/async_base_client.py` subclasses `AsyncGraphQLBase`. The hand-written async/sync primitive pairs
  (`AsyncLock`/`Lock`, `async_sleep`/`sleep`) are in `whitemarket/_concurrency.py`, outside both trees.
- `execute` takes `document` (the plugin renames ariadne's `query=` keyword) and returns the `data` object; variables
  reach the executor as plain JSON data (`to_plain`: models by alias without unset fields, enums as values,
  `Decimal` kept, a `float` or non-finite number refused). The plugin also rewrites `Model.model_validate(data)` to
  `self._decode(Model, data)`: a `ValidationError` becomes a `DecodeError` (path and reason of the first problem) that
  is raised outside the `except` block, so no `__context__` keeps the exception that holds the input.
- A raw `execute` without a declared operation type runs as a mutation (never retried). PHP infers `query` from a
  document that is clearly one; recorded in DEVIATIONS.md.
- `Secret`: the reveal method is `reveal()`; `str`, `repr` and `format` give `***`; a pydantic dump gives `***`; an
  empty value is allowed; equality is `hmac.compare_digest`; copy returns the same object; pickling is refused.
- `copy_code` (base model): `hide_input_in_errors=True` added; the hook raises if ariadne's template changed.
- unasync: whole-text regex table (`tools/unasync.py` `RULES`), then a token scan that fails on any surviving
  `async`, `await`, `asyncio`, `Async*`, `async_*`. The `_sync` tree is import-sorted and formatted by the dev ruff;
  `_generated/sync_client.py` and `base_client.py` are not reformatted (ruff excludes `_generated`).
- `graphql-core==3.2.14` is pinned in the `test` extra for the selection-invariant tests (tests only, the version the
  codegen environment resolves).
- Not changed: `_generated/__init__.py` (ariadne's) imports all 69 operation modules, so importing any generated
  module costs about 0.5 s. `defer_model_build` or a lazy `__init__` are options if that matters.
- Documents are sent as ariadne emits them (indented triple-quoted strings); no whitespace normalisation.

## Spike evidence (scratchpad, not committed)

`/private/tmp/claude-501/-Users-u-projects-whitemarket-sdk-python/6aa7585c-b2e0-44da-ab25-c3345d957483/scratchpad/codegen-spike/`:
`spike.toml` (config), `spike_plugins/whitemarket_codegen_plugin.py` (plugin), `spike_plugins/async_base_client_shim.py`,
`spike_plugins/unasync_spike.py`, `out/whitemarket/_runtime/*` (runtime stand-ins), `out/whitemarket/_generated/`
(output), `out/tests/test_spike.py` (10 tests, pass; breaking the discriminator or the enum fallback fails 2 resp. 1 of
them), `baseline.toml` + `out/baseline_client/` (stock output without plugin), `docs/` (ariadne docs at tag 0.19.0).

## Sources

- PyPI metadata: https://pypi.org/pypi/ariadne-codegen/0.19.0/json, https://pypi.org/project/ariadne-codegen/0.19.0/
- README at tag: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/README.md
- Configuration: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/03-reference/01-configuration.md
- Generated code dependencies: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/03-reference/02-generated-code-dependencies.md
- Custom scalars: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/02-guides/06-custom-scalars.md
- Async vs sync: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/02-guides/10-async-vs-sync.md
- Fragments and forward references: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/02-guides/14-fragments-and-forward-references.md
- Deprecation warnings: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/02-guides/16-deprecation-warnings.md
- Plugins: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/04-plugins/02-custom-plugins.md,
  https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/04-plugins/03-hooks.md
- Versioning policy: https://github.com/mirumee/ariadne-codegen/blob/0.19.0/docs/05-community/02-versioning-policy.md
- Source at tag (read in the installed 0.19.0 wheel): `ariadne_codegen/schema.py:288-303`, `settings.py:586-589`,
  `client_generators/constants.py:4-10`, `client_generators/result_fields.py:185-191, 367-398`;
  https://github.com/mirumee/ariadne-codegen/tree/0.19.0/ariadne_codegen
- pydantic 2.14 (installed 2.14.3): callable discriminators https://docs.pydantic.dev/2.14/concepts/unions/,
  `hide_input_in_errors` https://docs.pydantic.dev/2.14/api/config/, `Field(deprecated=...)`
  https://docs.pydantic.dev/2.14/concepts/fields/, `AwareDatetime` https://docs.pydantic.dev/2.14/api/types/
- unasync-style rewrite: https://github.com/encode/httpcore/blob/master/scripts/unasync.py
- PHP reference: `../whitemarket_sdk_php/docs/decisions/0001-codegen.md`, `0002-generated-layer-and-transport.md`,
  `docs/DEVIATIONS.md` (1.1 `FileUpload`)
- Type checkers used: mypy 2.4.1, pyright 1.1.414; Python 3.13.3 (checks run with `--python-version 3.11`)
