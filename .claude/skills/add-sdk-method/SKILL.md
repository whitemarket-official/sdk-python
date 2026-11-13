---
name: add-sdk-method
description: Use when adding or changing a high-level SDK method (market, buying, deals, selling, inventory, orders, wallet, profile, store, exports, live). Checklist from the SDK_SPEC entry through the generated operation, async implementation and generated sync mirror, mapper, errors, tests, README, example and CHANGELOG to a parity note for the sister SDKs.
---

# add-sdk-method: one high-level method, end to end

Every step is mandatory unless marked otherwise. Stop at the first step that cannot be satisfied and report it.

## 1. Spec entry

- The method exists in `docs/SDK_SPEC.md` section 3 (name, parameters, options, return type, GraphQL field). Not there -> **stop**: propose the SDK_SPEC change (via `clarify-spec` if non-trivial) and wait for approval (CLAUDE.md rule 18). Never add a public method the spec does not list.
- API facts (limits, statuses, error categories) come only from `docs/WHITEMARKET_API.md` with their source tags (rule 14). An open question there is not guessed.
- Check the sister SDKs for the same method (`../whitemarket_sdk_php` is the reference; read only) for naming and behaviour already settled.

## 2. Generated operation

- The operation exists in `graphql/operations/<query|mutation>/<field>.graphql` and the generated client method / models in `src/whitemarket/_generated/`. Missing or the selection is wrong/too deep -> add `graphql/overrides/<query|mutation>/<field>.graphql`, run `make codegen`, `make codegen-check` clean. Never edit generated files (rule 1).
- Query or mutation decides the retry behaviour: mutations are never retried (rule 2). Buying follows SDK_SPEC 3.3 reconciliation exactly.

## 3. Method and models

- Write the method **once**, in `src/whitemarket/_async/`; the sync variant on `WhiteMarketClient` comes from `make codegen` (`tools/unasync.py`). Never hand-write the sync copy.
- Find before you write (rule 11): reuse the existing paginator, mapper helpers, options dataclass, validators. A second class of an existing role needs a named reason.
- Signature in Python idiom with SDK_SPEC names in `snake_case` (rule 12): required inputs positional, options keyword-only (`*,`) or an options dataclass; full type annotations; tokens typed as the secret type.
- Client-side validation only where SDK_SPEC states a limit (comment length, lifetime, `custom_id` length); limits are module constants with the spec reference in a comment.
- Batch endpoints are used where they exist and lists are chunked at the documented size (rule 7). Pagination is a lazy generator (`AsyncIterator` in the core, `Iterator` in the sync mirror).
- Models: frozen (per the ADR), `Decimal` for money/wear, `str` for 64-bit ids, aware `datetime`, enums with an unknown fallback (rules 3, 5).

## 4. Mapper

- Generated pydantic model -> high-level model in one mapper per model, reused everywhere that model appears.
- `None` handling follows the schema nullability; a guard for a value the API model says is valid is pinned by a test (rule 0b).

## 5. Errors

- Map expected failures to the SDK_SPEC 1.5 hierarchy; branch on `extensions.category`, never `message` (rule 4). A new known category goes to the category enum with its source.
- Messages carry no tokens and no request bodies.

## 6. Tests (`Skill(testing)` first)

- Success through the HTTP boundary fake (respx or `httpx.MockTransport`): asserts request shape (`operationName`, variables) and the mapped model.
- **Both clients**: the async method and its generated sync counterpart (parametrize over both where the shape allows).
- Input matrix with boundaries for every validated parameter; GraphQL error with category; relevant HTTP statuses; for queries the retry path, for mutations exactly one request on 503.
- Pagination: stops on `hasNextPage = false`; batching: N-1/N/N+1 around the chunk size.
- Mapping test from a fixture, including unknown enum values and boundary numbers (`Decimal` with many places, id above 2^53).
- Break the implementation once and see each new test fail.

## 7. Docs and example

- README section for the method (SDK_SPEC 9 order), with a short runnable snippet for sync and async.
- Example under `examples/` if SDK_SPEC 9 lists one for this area; reads `WHITEMARKET_PARTNER_TOKEN` from the environment; read-only unless its name says `buy`/`sell`.
- Docstring on the public method: what it does, which exceptions it raises, whether it is retried.

## 8. CHANGELOG and contract

- `CHANGELOG.md` line under Added (or Changed/Breaking with `before -> after` per rule 16).
- Deviation from SDK_SPEC -> `docs/DEVIATIONS.md` line (rule 17); one affecting public API/retry/auth/money -> stop and ask first.

## 9. Readiness chain

`clean-code-review` (new public type or >100 lines) -> `quality-checks` -> `secure-coding` (if transport, auth, buying, live or export code was touched) -> claim.

## 10. Parity note

End the report with one line for the sister SDKs: what they must mirror (method, behaviour, test cases) and whether SDK_SPEC changed. Never edit the sister repos from here.

## Report

```
Method: client.<service>.<method>() -> <GraphQL field> (SDK_SPEC §x.y)
Files: path:line - what
Tests: <modules>, async + sync, red-on-broken checked
Checks: quality-checks <result>, secure-coding <result | N/A>
CHANGELOG / README / example: done | not needed (why)
Parity: <what sister SDKs must mirror>
Risks / open questions: <list>
```
