"""Bounds of the row decoders (SDK_SPEC 3.10 rules 10 to 12)."""

MAX_ROW_BYTES = 128 * 1024
"""A JSON row or a CSV record longer than this (as text, 128 KiB) is refused."""

MAX_ROW_DEPTH = 511
"""A JSON row nested deeper than this is refused (512 levels with the enclosing list)."""

PUSH_STEP = 4096
"""Input is handed to a parser in pieces of at most this many bytes.

It bounds what one step can produce (a few rows) and is the unit of the read-ahead past
`MAX_ROW_BYTES`: a JSON parser cannot report row boundaries, so a hostile row longer than
`MAX_ROW_BYTES + 3 * PUSH_STEP` is certainly refused, a shorter one over the cap possibly not.
"""
