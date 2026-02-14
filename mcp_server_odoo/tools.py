"""MCP tool definitions for Odoo operations."""

import base64
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import OdooConfig
from .connection import OdooConnection
from .utils import (
    get_smart_fields,
    parse_domain,
    parse_list_param,
    process_record_dates,
)

logger = logging.getLogger(__name__)


class ReadonlyError(Exception):
    """Raised when a write operation is attempted in readonly mode."""


def _check_write(config: OdooConfig) -> None:
    """Raise if readonly mode is on."""
    if config.readonly:
        raise ReadonlyError("Write operations are disabled. READONLY_MODE is enabled.")


def _safe_serialize(value: Any) -> Any:
    """Make sure the result is JSON-serializable."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_serialize(v) for k, v in value.items()}
    return str(value)


def register_tools(
    app: FastMCP,
    conn: OdooConnection,
    config: OdooConfig,
) -> None:
    """Register all MCP tools on the FastMCP app instance."""
    _register_read_tools(app, conn, config)
    _register_write_tools(app, conn, config)


def _register_read_tools(
    app: FastMCP,
    conn: OdooConnection,
    config: OdooConfig,
) -> None:
    """Register read-only tools."""

    # =================================================================
    # 1. search_records
    # =================================================================
    @app.tool()
    async def search_records(
        model: str,
        domain: str | list | None = None,
        fields: str | list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
        order: str | None = None,
    ) -> dict[str, Any]:
        """Search for records in an Odoo model.

        Args:
            model: Odoo model name, e.g. "res.partner", "sale.order".
            domain: Odoo domain filter as a list or JSON string.
                Examples:
                  [["is_company", "=", true]]
                  [["state", "=", "sale"], ["partner_id.country_id.code", "=", "TR"]]
                  [] or null for all records.
            fields: List of field names to return, or null for smart defaults.
                Use ["__all__"] to get every field (large!).
            limit: Max records to return (default 10).
            offset: Number of records to skip for pagination.
            order: Sort order, e.g. "name asc", "create_date desc".

        Returns:
            {"records": [...], "total": int, "limit": int, "offset": int, "model": str}
        """
        parsed_domain = parse_domain(domain)
        parsed_fields = parse_list_param(fields) if isinstance(fields, str) else fields

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
    @app.tool()
    async def read_record(
        model: str,
        record_id: int,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Read a single Odoo record by ID.

        Args:
            model: Odoo model name, e.g. "res.partner".
            record_id: The record ID to read.
            fields: Field names to return, or null for smart defaults.
                Use ["__all__"] for all fields.

        Returns:
            The record dict with requested fields.
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

        records = conn.read(model, [record_id], fields_to_fetch)
        if not records:
            raise ValueError(f"Record not found: {model} ID {record_id}")
        return process_record_dates(records[0])

    # =================================================================
    # 3. list_models
    # =================================================================
    @app.tool()
    async def list_models() -> dict[str, Any]:
        """List all Odoo models available in the database.

        Returns:
            {"models": [{"model": str, "name": str}],
             "total": int, "readonly": bool}
        """
        domain = [("transient", "=", False)]
        model_records = conn.search_read(
            "ir.model",
            domain,
            fields=["model", "name"],
            order="model ASC",
        )
        models = [{"model": r["model"], "name": r["name"]} for r in model_records]
        return {"models": models, "total": len(models), "readonly": config.readonly}

    # =================================================================
    # 4. get_record_count
    # =================================================================
    @app.tool()
    async def get_record_count(
        model: str,
        domain: str | list | None = None,
    ) -> dict[str, Any]:
        """Count records in an Odoo model matching a domain.

        Args:
            model: Odoo model name, e.g. "res.partner", "sale.order".
            domain: Odoo domain filter as a list or JSON string.
                Examples:
                  [["is_company", "=", true]]
                  [["state", "=", "sale"]]
                  [] or null for all records.

        Returns:
            {"model": str, "count": int}
        """
        parsed_domain = parse_domain(domain)
        count = conn.search_count(model, parsed_domain)
        return {"model": model, "count": count}

    # =================================================================
    # 5. get_model_fields
    # =================================================================
    @app.tool()
    async def get_model_fields(
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get field definitions for an Odoo model.

        Useful for discovering available fields before reading or
        searching records.

        Args:
            model: Odoo model name, e.g. "res.partner".
            attributes: Specific field attributes to return, e.g.
                ["string", "type", "required", "help"].
                If null, returns all attributes.

        Returns:
            {"model": str, "fields": {...}, "count": int}
        """
        fields_info = conn.fields_get(model, attributes)
        return {"model": model, "fields": fields_info, "count": len(fields_info)}

    # =================================================================
    # 6. save_binary_field
    # =================================================================
    @app.tool()
    async def save_binary_field(
        model: str,
        record_id: int,
        field: str,
        output_path: str,
    ) -> dict[str, Any]:
        """Save a binary/image field from an Odoo record directly to a file.

        Use this instead of read_record when you need to fetch large binary
        fields (like images, attachments). This avoids returning the large
        base64 data in the response - it writes the file to disk and returns
        only the file path and metadata.

        Args:
            model: Odoo model name, e.g. "hr.employee".
            field: Binary field name, e.g. "image_1920", "image_128".
            record_id: The record ID to read from.
            output_path: Absolute file path to save the binary data to.
                Parent directories will be created if needed.

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
        records = conn.read(model, [record_id], [field])
        if not records:
            raise ValueError(f"Record not found: {model} ID {record_id}")

        b64_data = records[0].get(field)
        if not b64_data:
            raise ValueError(
                f"Field '{field}' is empty on {model} ID {record_id}"
            )

        # Decode and save
        try:
            binary_data = base64.b64decode(b64_data)
        except Exception as exc:
            raise ValueError(f"Failed to decode base64 data: {exc}") from exc

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
    # 3. create_record
    # =================================================================
    @app.tool()
    async def create_record(
        model: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new record in an Odoo model.

        Args:
            model: Odoo model name, e.g. "res.partner".
            values: Field values for the new record.
                Example: {"name": "ACME Corp", "is_company": true}

        Returns:
            {"success": true, "id": int, "record": {...}, "url": str}
        """
        _check_write(config)
        if not values:
            raise ValueError("No values provided for record creation")
        record_id = conn.create(model, values)
        records = conn.read(model, [record_id], ["id", "name", "display_name"])
        record = process_record_dates(records[0]) if records else {"id": record_id}
        url = f"{config.url}/web#id={record_id}&model={model}&view_type=form"
        return {"success": True, "id": record_id, "record": record, "url": url}

    # =================================================================
    # 4. update_record
    # =================================================================
    @app.tool()
    async def update_record(
        model: str,
        record_id: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing Odoo record.

        Args:
            model: Odoo model name, e.g. "res.partner".
            record_id: The record ID to update.
            values: Field values to update.
                Example: {"email": "new@example.com", "phone": "+1234567890"}

        Returns:
            {"success": true, "id": int, "record": {...}, "url": str}
        """
        _check_write(config)
        if not values:
            raise ValueError("No values provided for record update")
        existing = conn.read(model, [record_id], ["id"])
        if not existing:
            raise ValueError(f"Record not found: {model} ID {record_id}")
        conn.write(model, [record_id], values)
        records = conn.read(model, [record_id], ["id", "name", "display_name"])
        record = process_record_dates(records[0]) if records else {"id": record_id}
        url = f"{config.url}/web#id={record_id}&model={model}&view_type=form"
        return {"success": True, "id": record_id, "record": record, "url": url}

    # =================================================================
    # 5. delete_record
    # =================================================================
    @app.tool()
    async def delete_record(
        model: str,
        record_id: int,
    ) -> dict[str, Any]:
        """Delete an Odoo record.

        Args:
            model: Odoo model name, e.g. "res.partner".
            record_id: The record ID to delete.

        Returns:
            {"success": true, "deleted_id": int, "deleted_name": str}
        """
        _check_write(config)
        existing = conn.read(model, [record_id], ["id", "name", "display_name"])
        if not existing:
            raise ValueError(f"Record not found: {model} ID {record_id}")
        name = (
            existing[0].get("name") or existing[0].get("display_name") or str(record_id)
        )
        conn.unlink(model, [record_id])
        return {"success": True, "deleted_id": record_id, "deleted_name": name}

    # =================================================================
    # 6. execute_method
    # =================================================================
    @app.tool()
    async def execute_method(
        model: str,
        method: str,
        record_ids: list[int],
        args: list | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a business method on Odoo records.

        Use this for triggering workflows and actions, e.g.
        confirming a sale order, validating a picking, posting an invoice.

        Args:
            model: Odoo model name, e.g. "sale.order".
            method: Method name to call, e.g. "action_confirm".
            record_ids: List of record IDs to call the method on.
            args: Optional extra positional arguments (rare).
            kwargs: Optional keyword arguments (rare).

        Returns:
            {"success": true, "model": str, "method": str,
             "record_ids": [...], "result": ...}

        Examples:
            Confirm a sale order:
                execute_method("sale.order", "action_confirm", [42])
            Validate a stock picking:
                execute_method("stock.picking", "button_validate", [15])
            Post an invoice:
                execute_method("account.move", "action_post", [100])
        """
        _check_write(config)
        call_args = [record_ids] + (args or [])
        result = conn.execute_kw(model, method, call_args, kwargs)
        return {
            "success": True,
            "model": model,
            "method": method,
            "record_ids": record_ids,
            "result": _safe_serialize(result),
        }
