"""TOON (Token-Oriented Object Notation) encoder using the `toons` library.

Converts structured Odoo data into a compact format
that reduces token usage compared to JSON.

Uses toons.dumps() with key_folding='table' for tabular record output
and delimiter='|' for pipe-separated values.
"""

from __future__ import annotations

import toons


def _preprocess_value(value: object) -> object:
    """Convert Odoo-specific types to toons-compatible values.

    - many2one ``[id, "name"]`` → ``"id:name"``
    - nested lists/dicts are recursively processed
    """
    if isinstance(value, list | tuple):
        # many2one: [id, "display_name"]
        if (
            len(value) == 2
            and isinstance(value[0], int)
            and isinstance(value[1], str)
        ):
            return f"{value[0]}:{value[1]}"
        return [_preprocess_value(v) for v in value]
    if isinstance(value, dict):
        return _preprocess(value)
    return value


def _preprocess(data: dict) -> dict:
    """Recursively pre-process all values in a dict."""
    return {k: _preprocess_value(v) for k, v in data.items()}


def toon_response(data: dict, record_key: str = "records") -> str:
    """Convert a full tool response dict to a TOON string.

    Uses ``key_folding='table'`` so that homogeneous record lists
    are rendered as compact header-row tables.
    """
    processed = _preprocess(data)
    return toons.dumps(processed, delimiter="|", key_folding="table")


def encode_single_record(record: dict) -> str:
    """Encode a single record as key:value lines."""
    processed = _preprocess(record)
    return toons.dumps(processed, delimiter="|")


def encode_fields(fields: dict, **metadata: object) -> str:
    """Encode Odoo field definitions dict into compact TOON format.

    Converts the nested ``{field_name: {type, string, ...}}`` dict into
    a list-of-dicts structure with a ``field`` column, then renders
    as a table via ``key_folding='table'``.

    Extra keyword arguments are included as top-level metadata
    (e.g. ``model='res.partner'``).
    """
    rows = [
        {"field": name, **attrs}
        for name, attrs in fields.items()
        if isinstance(attrs, dict)
    ]
    data: dict = {"fields": rows, "count": len(rows), **metadata}
    processed = _preprocess(data)
    return toons.dumps(processed, delimiter="|", key_folding="table")
