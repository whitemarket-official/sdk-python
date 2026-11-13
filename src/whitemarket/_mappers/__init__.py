"""Pure mappers from generated result models to high-level models (SDK_SPEC 4).

One mapper per model, in one place; every operation has its own generated classes with the same
fields, so the mappers take structural types (protocols) instead of class lists. No IO here: the
async and sync clients share this package.
"""
