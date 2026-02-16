"""TOON (Token-Oriented Object Notation) encoder.

Converts structured Odoo data into a compact header-row format
that reduces token usage by ~40-60% compared to JSON.

Format example:
    records[2]{id|name|amount}
    1|SO001|500
    2|SO002|300
    ~
    total:2 limit:10 offset:0 model:sale.order
"""

from __future__ import annotations


def encode_value(value: object) -> str:
    """Encode a single value to its TOON string representation.

    - None          → ``~``
    - bool          → ``T`` / ``F``
    - many2one list → ``id:name``  (e.g. ``[4, "Agrolait"]`` → ``4:Agrolait``)
    - list/tuple    → comma-joined encoded values
    - everything else → str()
    """
    if value is None or value is False:
        return "~"
    if value is True:
        return "T"
    if isinstance(value, list | tuple):
        # many2one: [id, "display_name"]
        if (
            len(value) == 2
            and isinstance(value[0], int)
            and isinstance(value[1], str)
        ):
            return f"{value[0]}:{value[1]}"
        # generic list (many2many ids, etc.)
        return ",".join(encode_value(v) for v in value)
    return str(value)


def encode_records(records: list[dict], record_key: str = "records") -> str:
    """Encode a list of record dicts into TOON header-row format.

    Returns a string like::

        records[3]{id|name|amount}
        1|SO001|500
        2|SO002|300
        3|SO003|700
    """
    if not records:
        return f"{record_key}[0]{{}}"

    headers = list(records[0].keys())
    header_line = f"{record_key}[{len(records)}]{{{"|".join(headers)}}}"

    rows: list[str] = []
    for rec in records:
        row = "|".join(encode_value(rec.get(h)) for h in headers)
        rows.append(row)

    return "\n".join([header_line, *rows])


def encode_metadata(data: dict, exclude_keys: set[str] | None = None) -> str:
    """Encode metadata key-value pairs into a single TOON line.

    Example: ``total:5 limit:10 offset:0 model:sale.order``
    """
    exclude = exclude_keys or set()
    parts = []
    for k, v in data.items():
        if k in exclude:
            continue
        parts.append(f"{k}:{encode_value(v)}")
    return " ".join(parts)


def encode_fields(fields: dict) -> str:
    """Encode Odoo field definitions dict into compact TOON format.

    Converts the nested ``{field_name: {type, string, ...}}`` dict into
    a header-row table.
    """
    if not fields:
        return "fields[0]{}"

    # Collect all attribute keys across fields for consistent columns
    attr_keys: list[str] = []
    for field_attrs in fields.values():
        if isinstance(field_attrs, dict):
            for k in field_attrs:
                if k not in attr_keys:
                    attr_keys.append(k)

    headers = ["field"] + attr_keys
    header_line = f"fields[{len(fields)}]{{{"|".join(headers)}}}"

    rows: list[str] = []
    for field_name, field_attrs in fields.items():
        if not isinstance(field_attrs, dict):
            continue
        values = [field_name] + [
            encode_value(field_attrs.get(k)) for k in attr_keys
        ]
        rows.append("|".join(values))

    return "\n".join([header_line, *rows])


def encode_single_record(record: dict) -> str:
    """Encode a single record as key:value lines.

    Example::

        id:42
        name:Agrolait
        email:agrolait@example.com
    """
    lines: list[str] = []
    for k, v in record.items():
        lines.append(f"{k}:{encode_value(v)}")
    return "\n".join(lines)


def toon_response(data: dict, record_key: str = "records") -> str:
    """Convert a full tool response dict to a TOON string.

    Expects *data* to contain a list under *record_key* plus optional
    metadata keys.  The output separates the record block from metadata
    with a ``~`` line.
    """
    records = data.get(record_key, [])
    meta_exclude = {record_key}

    parts: list[str] = [encode_records(records, record_key)]

    meta = encode_metadata(data, exclude_keys=meta_exclude)
    if meta:
        parts.append("~")
        parts.append(meta)

    return "\n".join(parts)
