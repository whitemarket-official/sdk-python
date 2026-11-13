# Deviations from SDK_SPEC (Python)

Every place where this SDK deviates from [`SDK_SPEC.md`](SDK_SPEC.md), with the reason (CLAUDE.md rule 17).

| Spec section | What the spec requires | Why it does not fit Python (fact) | What this SDK does |
|---|---|---|---|
| 1.5 "Errors" | `NotFoundError` when "category ends with `.not_found`" | The spec does not say which error of a multi-error response decides | `NotFoundError` only when EVERY error's category ends with `.not_found`; a mix (or an answer with no errors) gives a plain `GraphQLError` (`GraphQLError.has_category()` finds a category in any error). Same as PHP; proposed for SDK_SPEC clarification |
| 1.1 "Generated layer": `execute(document, variables)` | A raw document is run with the type the caller declares | PHP infers `query` from a document that is clearly one; Python does not parse documents | `execute(document, variables=None, operation_name=None, *, operation_type=None)`: no declared type means mutation, never retried (CLAUDE.md rule 2); the caller declares `operation_type="query"` to allow retries |
