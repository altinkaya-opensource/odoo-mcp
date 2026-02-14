"""MCP tool definitions for Odoo operations."""

import base64
import logging
import os
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .config import OdooConfig
from .connection import OdooConnection, OdooConnectionError
from .utils import (
    DomainValidationError,
    get_smart_fields,
    parse_domain,
    parse_list_param,
    process_record_dates,
)

logger = logging.getLogger(__name__)

# -- Shared constants and helpers ------------------------------------------

DOMAIN_DESCRIPTION = (
    "Odoo domain filter. A list of conditions where each condition is "
    "[field_name, operator, value]. "
    "Multiple conditions are implicitly ANDed. "
    "Use '|' prefix for OR: ['|', [cond1], [cond2]]. "
    "Use '!' prefix for NOT: ['!', [cond]]. "
    "Operators: =, !=, <, >, <=, >=, ilike (case-insensitive contains), "
    "like, not like, not ilike, in, not in, child_of, parent_of. "
    "Dot notation for relations: 'partner_id.country_id.code'. "
    "Examples: "
    '[["is_company", "=", true]] | '
    '[["state", "in", ["draft", "sent"]]] | '
    '["|", ["name", "ilike", "acme"], ["ref", "ilike", "acme"]] | '
    "[] for all records."
)

MODEL_DESCRIPTION = (
    "Odoo model technical name. "
    "Examples: 'res.partner', 'sale.order', 'sale.order.line', "
    "'purchase.order', 'account.move', 'account.move.line', "
    "'product.product', 'product.template', 'stock.picking', "
    "'stock.move', 'mrp.production', 'project.task'"
)


def _check_write(config: OdooConfig) -> None:
    """Raise ToolError if readonly mode is on."""
    if config.readonly:
        raise ToolError(
            "Write operations are disabled (READONLY_MODE is enabled). "
            "This server is configured for read-only access."
        )


def _handle_odoo_error(exc: OdooConnectionError, context: str) -> ToolError:
    """Convert OdooConnectionError to ToolError with helpful context."""
    msg = str(exc)
    if "Access" in msg or "security" in msg.lower():
        return ToolError(f"Access denied while {context}: {msg}")
    return ToolError(f"Odoo error while {context}: {msg}")


def _safe_serialize(value: Any) -> Any:
    """Make sure the result is JSON-serializable."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_serialize(v) for k, v in value.items()}
    return str(value)


def _parse_domain_safe(domain: str | list | None) -> list:
    """Parse domain and convert validation errors to ToolError."""
    try:
        return parse_domain(domain)
    except (ValueError, DomainValidationError) as exc:
        raise ToolError(str(exc)) from exc


# -- Tool registration ----------------------------------------------------


def register_tools(
    app: FastMCP,
    conn: OdooConnection,
    config: OdooConfig,
) -> None:
    """Register all MCP tools on the FastMCP app instance."""
    _register_search_tools(app, conn)
    _register_model_tools(app, conn, config)
    _register_write_tools(app, conn, config)


def _register_search_tools(
    app: FastMCP,
    conn: OdooConnection,
) -> None:
    """Register search and read tools."""

    # =================================================================
    # 1. search_records
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        timeout=60.0,
    )
    async def search_records(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        domain: Annotated[
            str | list | None,
            Field(description=DOMAIN_DESCRIPTION),
        ] = None,
        fields: Annotated[
            str | list[str] | None,
            Field(
                description=(
                    "Field names to return. null for smart defaults (recommended), "
                    "or a list like ['name', 'state', 'partner_id']. "
                    "Use ['__all__'] to fetch every field (can be large)."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Maximum number of records to return.", ge=1, le=500),
        ] = 10,
        offset: Annotated[
            int,
            Field(description="Number of records to skip (for pagination).", ge=0),
        ] = 0,
        order: Annotated[
            str | None,
            Field(
                description=(
                    "Sort order. Examples: 'name asc', 'create_date desc', "
                    "'amount_total desc, name asc'."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Search for records in an Odoo model with domain filtering,
        field selection, pagination, and sorting.

        Returns a dict with keys:
          - records: list of record dicts with the requested fields
          - total: total count of records matching the domain (ignoring limit/offset)
          - limit, offset, model: echo of the parameters used
        """
        parsed_domain = _parse_domain_safe(domain)
        parsed_fields = parse_list_param(fields) if isinstance(fields, str) else fields

        try:
            total = conn.search_count(model, parsed_domain)

            fields_to_fetch = parsed_fields
            if parsed_fields is None:
                try:
                    fi = conn.fields_get(model)
                    fields_to_fetch = get_smart_fields(fi)
                except Exception:
                    fields_to_fetch = None
            elif parsed_fields == ["__all__"]:
                fields_to_fetch = None

            records = conn.search_read(
                model,
                parsed_domain,
                fields=fields_to_fetch,
                limit=limit,
                offset=offset,
                order=order,
            )
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"searching {model}") from exc

        records = [process_record_dates(r) for r in records]
        return {
            "records": records,
            "total": total,
            "limit": limit,
            "offset": offset,
            "model": model,
        }

    # =================================================================
    # 2. read_record
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        timeout=30.0,
    )
    async def read_record(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        record_id: Annotated[
            int,
            Field(description="The numeric ID of the record to read.", ge=1),
        ],
        fields: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Field names to return. null for smart defaults, "
                    "or ['__all__'] for every field."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read a single Odoo record by its ID.

        Returns the record as a dict with the requested fields.
        Raises an error if the record does not exist.
        """
        fields_to_fetch = fields
        if fields is None:
            try:
                fi = conn.fields_get(model)
                fields_to_fetch = get_smart_fields(fi)
            except Exception:
                fields_to_fetch = None
        elif fields == ["__all__"]:
            fields_to_fetch = None

        try:
            records = conn.read(model, [record_id], fields_to_fetch)
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"reading {model} ID {record_id}") from exc

        if not records:
            raise ToolError(f"Record not found: {model} with ID {record_id}")
        return process_record_dates(records[0])


def _register_model_tools(
    app: FastMCP,
    conn: OdooConnection,
    config: OdooConfig,
) -> None:
    """Register model discovery and counting tools."""

    # =================================================================
    # 3. list_models
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        timeout=30.0,
    )
    async def list_models() -> dict[str, Any]:
        """List all non-transient Odoo models available in the database.

        Use this to discover which models exist before searching or
        reading records.

        Returns a dict with:
          - models: list of {model: str, name: str} dicts
          - total: number of models
          - readonly: whether the server is in read-only mode
        """
        try:
            domain = [("transient", "=", False)]
            model_records = conn.search_read(
                "ir.model",
                domain,
                fields=["model", "name"],
                order="model ASC",
            )
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, "listing models") from exc

        models = [{"model": r["model"], "name": r["name"]} for r in model_records]
        return {"models": models, "total": len(models), "readonly": config.readonly}

    # =================================================================
    # 4. get_record_count
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        timeout=30.0,
    )
    async def get_record_count(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        domain: Annotated[
            str | list | None,
            Field(description=DOMAIN_DESCRIPTION),
        ] = None,
    ) -> dict[str, Any]:
        """Count records matching a domain filter.
        Lightweight -- fetches no record data, only the count.

        Returns: {"model": str, "count": int}
        """
        parsed_domain = _parse_domain_safe(domain)

        try:
            count = conn.search_count(model, parsed_domain)
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"counting {model}") from exc

        return {"model": model, "count": count}

    # =================================================================
    # 5. get_model_fields
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        timeout=30.0,
    )
    async def get_model_fields(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        attributes: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Specific field attributes to return. "
                    "Examples: ['string', 'type', 'required', 'help', 'selection']. "
                    "null returns all attributes."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get field definitions for an Odoo model.

        Use this to discover available fields, their types, and constraints
        before constructing search domains or creating/updating records.

        Returns: {"model": str, "fields": {field_name: {attr: value}}, "count": int}
        """
        try:
            fields_info = conn.fields_get(model, attributes)
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"getting fields for {model}") from exc

        return {"model": model, "fields": fields_info, "count": len(fields_info)}

    # =================================================================
    # 6. save_binary_field
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": False, "openWorldHint": False},
        timeout=30.0,
    )
    async def save_binary_field(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        record_id: Annotated[
            int,
            Field(description="The numeric ID of the record to read from.", ge=1),
        ],
        field: Annotated[
            str,
            Field(
                description=(
                    "Binary field name to read, e.g. 'image_1920', 'image_128'."
                ),
            ),
        ],
        output_path: Annotated[
            str,
            Field(
                description=(
                    "Absolute file path to save the binary data to. "
                    "Parent directories will be created if needed."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Save a binary/image field from an Odoo record directly to a file.

        Use this instead of read_record when you need to fetch large binary
        fields (like images, attachments). This avoids returning the large
        base64 data in the response - it writes the file to disk and returns
        only the file path and metadata.

        Returns:
            {"success": true, "path": str, "size_bytes": int, "model": str,
             "record_id": int, "field": str}

        Examples:
            Save employee photo:
                save_binary_field("hr.employee", 11, "image_1920",
                    "/Users/me/output/photo.png")
            Save product image:
                save_binary_field("product.product", 42, "image_1920",
                    "/tmp/product_image.png")
        """
        try:
            records = conn.read(model, [record_id], [field])
        except OdooConnectionError as exc:
            raise _handle_odoo_error(
                exc, f"reading {model} ID {record_id}"
            ) from exc

        if not records:
            raise ToolError(f"Record not found: {model} with ID {record_id}")

        b64_data = records[0].get(field)
        if not b64_data:
            raise ToolError(
                f"Field '{field}' is empty on {model} ID {record_id}"
            )

        try:
            binary_data = base64.b64decode(b64_data)
        except Exception as exc:
            raise ToolError(f"Failed to decode base64 data: {exc}") from exc

        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(binary_data)

        size_bytes = len(binary_data)
        logger.info(
            "Saved %s.%s (ID %d) to %s (%d bytes)",
            model, field, record_id, output_path, size_bytes,
        )

        return {
            "success": True,
            "path": output_path,
            "size_bytes": size_bytes,
            "model": model,
            "record_id": record_id,
            "field": field,
        }


def _register_write_tools(
    app: FastMCP,
    conn: OdooConnection,
    config: OdooConfig,
) -> None:
    """Register write/mutating tools."""

    # =================================================================
    # 6. create_record
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        timeout=30.0,
    )
    async def create_record(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        values: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Field values for the new record as a dict. "
                    "Example: {'name': 'ACME Corp', 'is_company': true, "
                    "'email': 'info@acme.com'}. "
                    "Use get_model_fields first to discover required fields."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Create a new record in an Odoo model.

        Returns: {"success": true, "id": int, "record": {...}, "url": str}
        The url links directly to the record in the Odoo web interface.
        """
        _check_write(config)
        if not values:
            raise ToolError(
                "No values provided for record creation. "
                "Provide a dict of field values."
            )

        try:
            record_id = conn.create(model, values)
            records = conn.read(model, [record_id], ["id", "name", "display_name"])
            record = process_record_dates(records[0]) if records else {"id": record_id}
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"creating {model}") from exc

        url = f"{config.url}/web#id={record_id}&model={model}&view_type=form"
        return {"success": True, "id": record_id, "record": record, "url": url}

    # =================================================================
    # 7. update_record
    # =================================================================
    @app.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        timeout=30.0,
    )
    async def update_record(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        record_id: Annotated[
            int,
            Field(description="The numeric ID of the record to update.", ge=1),
        ],
        values: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Field values to update as a dict. "
                    "Only include fields you want to change. "
                    "Example: {'email': 'new@example.com', "
                    "'phone': '+90 312 555 0000'}"
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Update fields on an existing Odoo record.

        Returns: {"success": true, "id": int, "record": {...}, "url": str}
        Raises an error if the record does not exist.
        """
        _check_write(config)
        if not values:
            raise ToolError(
                "No values provided for record update. "
                "Provide a dict of field values to change."
            )

        try:
            existing = conn.read(model, [record_id], ["id"])
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"updating {model} ID {record_id}") from exc

        if not existing:
            raise ToolError(f"Record not found: {model} with ID {record_id}")

        try:
            conn.write(model, [record_id], values)
            records = conn.read(model, [record_id], ["id", "name", "display_name"])
            record = process_record_dates(records[0]) if records else {"id": record_id}
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"updating {model} ID {record_id}") from exc

        url = f"{config.url}/web#id={record_id}&model={model}&view_type=form"
        return {"success": True, "id": record_id, "record": record, "url": url}

    # =================================================================
    # 8. delete_record
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": False, "destructiveHint": True},
        timeout=30.0,
    )
    async def delete_record(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        record_id: Annotated[
            int,
            Field(description="The numeric ID of the record to delete.", ge=1),
        ],
    ) -> dict[str, Any]:
        """Permanently delete an Odoo record. This action cannot be undone.

        Returns: {"success": true, "deleted_id": int, "deleted_name": str}
        Raises an error if the record does not exist.
        """
        _check_write(config)

        try:
            existing = conn.read(model, [record_id], ["id", "name", "display_name"])
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"deleting {model} ID {record_id}") from exc

        if not existing:
            raise ToolError(f"Record not found: {model} with ID {record_id}")

        name = (
            existing[0].get("name") or existing[0].get("display_name") or str(record_id)
        )

        try:
            conn.unlink(model, [record_id])
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"deleting {model} ID {record_id}") from exc

        return {"success": True, "deleted_id": record_id, "deleted_name": name}

    # =================================================================
    # 9. execute_method
    # =================================================================
    @app.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        timeout=120.0,
    )
    async def execute_method(
        model: Annotated[str, Field(description=MODEL_DESCRIPTION)],
        method: Annotated[
            str,
            Field(
                description=(
                    "Method name to call on the records. Common examples: "
                    "'action_confirm' (confirm sale/purchase orders), "
                    "'button_validate' (validate stock pickings), "
                    "'action_post' (post journal entries/invoices), "
                    "'action_cancel' (cancel documents), "
                    "'action_draft' (reset to draft)."
                ),
            ),
        ],
        record_ids: Annotated[
            list[int],
            Field(
                description=(
                    "List of record IDs to call the method on. "
                    "Example: [42] or [1, 2, 3]."
                ),
                min_length=1,
            ),
        ],
        args: Annotated[
            list | None,
            Field(
                description=(
                    "Extra positional arguments for the method " "(rarely needed)."
                ),
            ),
        ] = None,
        kwargs: Annotated[
            dict[str, Any] | None,
            Field(
                description="Keyword arguments for the method (rarely needed).",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Call a business method on Odoo records.

        Use this for triggering workflows and actions like confirming orders,
        validating pickings, posting invoices, etc.

        Returns: {"success": true, "model": str, "method": str,
                  "record_ids": [...], "result": ...}

        Common usage patterns:
          Confirm sale order: execute_method("sale.order", "action_confirm", [42])
          Validate picking: execute_method("stock.picking", "button_validate", [15])
          Post invoice: execute_method("account.move", "action_post", [100])
        """
        _check_write(config)

        try:
            call_args = [record_ids] + (args or [])
            result = conn.execute_kw(model, method, call_args, kwargs)
        except OdooConnectionError as exc:
            raise _handle_odoo_error(exc, f"calling {model}.{method}") from exc

        return {
            "success": True,
            "model": model,
            "method": method,
            "record_ids": record_ids,
            "result": _safe_serialize(result),
        }
