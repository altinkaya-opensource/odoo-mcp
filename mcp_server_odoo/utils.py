"""Shared formatting and error helpers."""

import ast
import json
from datetime import datetime
from typing import Any

# -- Domain validation constants -------------------------------------------

VALID_OPERATORS = frozenset(
    {
        "=",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
        "like",
        "ilike",
        "not like",
        "not ilike",
        "=like",
        "=ilike",
        "in",
        "not in",
        "child_of",
        "parent_of",
        "=?",
    }
)

DOMAIN_LOGIC_OPS = frozenset({"&", "|", "!"})


class DomainValidationError(ValueError):
    """Raised when a domain has structural or semantic errors.

    The message is designed to be helpful to an LLM, explaining
    what went wrong and how to fix it.
    """


def validate_domain(domain: list) -> list:
    """Validate an Odoo domain for structural correctness.

    Checks:
    1. Each leaf is a list/tuple of exactly 3 elements: [field, operator, value]
    2. The operator in each leaf is from the known set
    3. Polish notation structure is correct ('&'/'|' consume 2 operands, '!' consumes 1)
    4. Field names are non-empty strings
    5. 'in' and 'not in' operators have list/tuple values

    Returns the domain unchanged if valid.
    Raises DomainValidationError with a helpful message if invalid.
    """
    if not domain:
        return domain

    for i, element in enumerate(domain):
        if isinstance(element, str):
            if element not in DOMAIN_LOGIC_OPS:
                raise DomainValidationError(
                    f"Domain element at index {i} is a string '{element}' "
                    f"but is not a valid logic operator. "
                    f"Valid logic operators are: & (AND), | (OR), ! (NOT). "
                    f"If you meant this as a condition, wrap it in a leaf: "
                    f"['{element}', '=', value]."
                )
            continue

        if not isinstance(element, list | tuple):
            raise DomainValidationError(
                f"Domain element at index {i} has type {type(element).__name__} "
                f"but must be a list of 3 elements [field, operator, value] "
                f"or a logic operator string ('&', '|', '!')."
            )

        if len(element) != 3:
            raise DomainValidationError(
                f"Domain leaf at index {i} has {len(element)} elements: {element!r}. "
                f"Each leaf must have exactly 3 elements: "
                f"[field_name, operator, value]. "
                f"Example: ['name', 'ilike', 'acme']."
            )

        field_name, operator, value = element

        if not isinstance(field_name, str) or not field_name.strip():
            raise DomainValidationError(
                f"Domain leaf at index {i}: field name must be a non-empty string, "
                f"got {field_name!r}. "
                f"Example: 'partner_id.name', 'state', 'amount_total'."
            )

        if not isinstance(operator, str):
            raise DomainValidationError(
                f"Domain leaf at index {i}: operator must be a string, "
                f"got {type(operator).__name__} ({operator!r}). "
                f"Valid operators: {', '.join(sorted(VALID_OPERATORS))}."
            )

        if operator not in VALID_OPERATORS:
            raise DomainValidationError(
                f"Domain leaf at index {i}: unknown operator '{operator}'. "
                f"Valid operators: {', '.join(sorted(VALID_OPERATORS))}. "
                f"Common ones: = (equals), != (not equals), "
                f"ilike (case-insensitive contains), "
                f"in (value in list), not in (value not in list)."
            )

        if operator in ("in", "not in") and not isinstance(value, list | tuple):
            raise DomainValidationError(
                f"Domain leaf at index {i}: operator '{operator}' requires "
                f"a list value, got {type(value).__name__} ({value!r}). "
                f"Example: ['state', 'in', ['draft', 'sent']]."
            )

    _validate_polish_notation(domain)

    return domain


def _validate_polish_notation(domain: list) -> None:
    """Validate that Polish notation operators consume the correct number of operands.

    In Odoo domains:
    - '&' and '|' are binary: they combine the next 2 operands
    - '!' is unary: it negates the next 1 operand
    - An "operand" is either a leaf or a sub-expression produced by another operator
    - Multiple bare leaves without operators have implicit '&' between them

    Uses a counter approach: each binary op needs 2 operands and produces 1 (net -1),
    each unary op needs 1 and produces 1 (net 0), each leaf produces 1 (net +1).
    A valid domain must have a final counter >= 1.
    """
    counter = 0
    for element in domain:
        if isinstance(element, str) and element in DOMAIN_LOGIC_OPS:
            if element == "!":
                pass  # needs 1, produces 1 => net 0
            else:
                counter -= 1  # needs 2 operands, produces 1 => net -1
        else:
            counter += 1  # leaf produces 1 operand

    # In valid Polish notation the final counter must be >= 1.
    # counter < 1 means there are more operators than leaves can satisfy.
    if counter < 1:
        raise DomainValidationError(
            "Domain has too many operators for the number of conditions. "
            "Each '&' or '|' needs exactly 2 conditions after it. "
            "Each '!' needs exactly 1 condition after it. "
            "Example: ['|', ['state','=','draft'], ['state','=','sent']] "
            "means state is draft OR sent."
        )


# -- Domain parsing --------------------------------------------------------


def parse_domain(domain: str | list | None) -> list:
    """Parse and validate a domain that may be a JSON string, Python repr, or list."""
    if domain is None:
        return []
    if isinstance(domain, list):
        return validate_domain(domain)
    # Try JSON first
    try:
        result = json.loads(domain)
        if isinstance(result, list):
            return validate_domain(result)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try Python literal (handles single quotes, True/False)
    try:
        result = ast.literal_eval(domain)
        if isinstance(result, list):
            return validate_domain(result)
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


# -- Date formatting -------------------------------------------------------


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
