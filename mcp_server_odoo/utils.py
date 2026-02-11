"""Shared formatting and error helpers."""

import ast
import json
from datetime import datetime
from typing import Any


def parse_domain(domain: str | list | None) -> list:
    """Parse a domain that may be a JSON string, Python repr, or list."""
    if domain is None:
        return []
    if isinstance(domain, list):
        return domain
    # Try JSON first
    try:
        result = json.loads(domain)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    # Try Python literal (handles single quotes, True/False)
    try:
        result = ast.literal_eval(domain)
        if isinstance(result, list):
            return result
    except (ValueError, SyntaxError):
        pass
    raise ValueError(
        f"Invalid domain: expected JSON or Python list, got: {domain[:120]}"
    )


def parse_list_param(value: str | list | None) -> list | None:
    """Parse a parameter that may be a JSON string or list."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    try:
        result = json.loads(value)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        result = ast.literal_eval(value)
        if isinstance(result, list):
            return result
    except (ValueError, SyntaxError):
        pass
    raise ValueError(f"Expected JSON or Python list, got: {value[:120]}")


def format_datetime(value: str) -> str:
    """Convert Odoo datetime strings to ISO 8601."""
    if not value or not isinstance(value, str):
        return value
    # 2025-06-07 21:55:52 -> ISO
    if " " in value and len(value) == 19:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except ValueError:
            pass
    return value


def process_record_dates(record: dict[str, Any]) -> dict[str, Any]:
    """Format known datetime fields in a record dict."""
    datetime_hints = {
        "create_date",
        "write_date",
        "date_order",
        "date_invoice",
        "date_due",
        "date_start",
        "date_end",
        "date_from",
        "date_to",
        "last_used_at",
        "expires_at",
    }
    for key, val in record.items():
        if isinstance(val, str) and (
            key in datetime_hints or key.endswith("_date") or key.endswith("_datetime")
        ):
            record[key] = format_datetime(val)
    return record


# -- Smart field selection ------------------------------------------------

# Fields always included
ESSENTIAL_FIELDS = {"id", "name", "display_name", "active"}

# Prefixes to exclude
EXCLUDE_PREFIXES = ("_", "message_", "activity_", "website_message_")

# Specific fields to exclude
EXCLUDE_FIELDS = {
    "write_date",
    "create_date",
    "write_uid",
    "create_uid",
    "__last_update",
    "access_token",
    "access_warning",
    "access_url",
}

# Heavy field types
HEAVY_TYPES = {"binary", "image", "html", "one2many", "many2many"}

MAX_SMART_FIELDS = 40


def get_smart_fields(fields_info: dict[str, dict[str, Any]]) -> list[str]:
    """Pick the most useful fields from a model's fields_get result."""
    scored: list[tuple] = []
    for name, info in fields_info.items():
        if name in ESSENTIAL_FIELDS:
            scored.append((name, 1000))
            continue
        if name.startswith(EXCLUDE_PREFIXES) or name in EXCLUDE_FIELDS:
            continue
        ftype = info.get("type", "")
        if ftype in HEAVY_TYPES:
            continue
        if info.get("compute") and not info.get("store", True):
            continue
        score = 0
        if info.get("required"):
            score += 500
        type_scores = {
            "char": 200,
            "boolean": 180,
            "selection": 170,
            "integer": 160,
            "float": 160,
            "monetary": 140,
            "date": 150,
            "datetime": 150,
            "many2one": 120,
            "text": 80,
        }
        score += type_scores.get(ftype, 50)
        if info.get("store", True):
            score += 80
        patterns = [
            "state",
            "status",
            "stage",
            "priority",
            "amount",
            "total",
            "date",
            "user",
            "partner",
            "email",
            "phone",
            "code",
            "ref",
        ]
        if any(p in name.lower() for p in patterns):
            score += 60
        scored.append((name, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scored[:MAX_SMART_FIELDS]]
