"""Regression tests for field metadata through the registered MCP tool."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastmcp import Client, FastMCP

from mcp_server_odoo.connection import OdooConnection, OdooConnectionError
from mcp_server_odoo.tools import register_tools


class TestGetModelFields(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = Mock(spec=OdooConnection)
        self.conn.fields_get = AsyncMock()
        self.app = FastMCP("test-odoo")
        register_tools(
            self.app, self.conn, SimpleNamespace(readonly=True, default_limit=10)
        )

    async def test_returns_awaited_metadata(self):
        fields = {"name": {"string": "Name", "type": "char"}}
        for attributes in (None, ["string", "type"]):
            for metadata in (fields, {}):
                with self.subTest(attributes=attributes, metadata=metadata):
                    self.conn.fields_get.reset_mock()
                    self.conn.fields_get.return_value = metadata
                    params = {"model": "res.partner"}
                    if attributes is not None:
                        params["attributes"] = attributes
                    async with Client(self.app) as client:
                        result = await client.call_tool("get_model_fields", params)
                    self.conn.fields_get.assert_awaited_once_with(
                        "res.partner", attributes
                    )
                    self.assertEqual(
                        result.data,
                        {
                            "model": "res.partner",
                            "fields": metadata,
                            "count": len(metadata),
                        },
                    )

    async def test_converts_async_connection_errors(self):
        for message, prefix in (
            ("RPC unavailable", "Odoo error"),
            ("Access denied", "Access denied"),
        ):
            with self.subTest(message=message):
                self.conn.fields_get.reset_mock()
                self.conn.fields_get.side_effect = OdooConnectionError(message)
                async with Client(self.app) as client:
                    result = await client.call_tool(
                        "get_model_fields",
                        {"model": "res.partner"},
                        raise_on_error=False,
                    )
                self.conn.fields_get.assert_awaited_once_with("res.partner", None)
                self.assertTrue(result.is_error)
                self.assertEqual(
                    result.content[0].text,
                    f"{prefix} while getting fields for res.partner: {message}",
                )
