"""Tests for the read-only-safe download_binary_field tool."""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastmcp import Client, FastMCP
from mcp_server_odoo.connection import OdooConnection
from mcp_server_odoo.tools import register_tools


class TestDownloadBinaryField(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.download_dir = os.path.join(self.temp_dir.name, "downloads")
        self.conn = Mock(spec=OdooConnection)
        self.conn.read = AsyncMock(
            return_value=[{"image": base64.b64encode(b"hello").decode()}]
        )
        self.app = FastMCP("test-odoo")
        register_tools(
            self.app,
            self.conn,
            SimpleNamespace(
                readonly=True,
                default_limit=10,
                download_dir=self.download_dir,
            ),
        )

    async def call_download(self, **params):
        async with Client(self.app) as client:
            return await client.call_tool(
                "download_binary_field", params, raise_on_error=False
            )

    def resolved_download_dir(self):
        return os.path.realpath(self.download_dir)

    async def test_downloads_to_configured_directory(self):
        result = await self.call_download(
            model="res.partner",
            record_id=7,
            field="image",
            filename="avatar.png",
        )

        self.assertFalse(result.is_error)
        expected_path = os.path.join(self.resolved_download_dir(), "avatar.png")
        self.assertEqual(result.data["path"], expected_path)
        self.assertEqual(result.data["size_bytes"], 5)
        self.assertEqual(result.data["model"], "res.partner")
        self.assertEqual(result.data["record_id"], 7)
        self.assertEqual(result.data["field"], "image")
        self.assertEqual(Path(expected_path).read_bytes(), b"hello")
        self.assertTrue(os.path.isdir(self.resolved_download_dir()))
        if os.name == "posix":
            self.assertEqual(os.stat(expected_path).st_mode & 0o777, 0o600)

    async def test_generates_default_filename(self):
        result = await self.call_download(
            model="res.partner", record_id=7, field="image"
        )

        self.assertFalse(result.is_error)
        self.assertEqual(
            os.path.basename(result.data["path"]), "res_partner_7_image.bin"
        )
        self.assertEqual(Path(result.data["path"]).read_bytes(), b"hello")

    async def test_rejects_paths_in_filename(self):
        for filename in (
            "../escape.png",
            "sub/escape.png",
            "/tmp/escape.png",
            "..",
            "",
            "bad\\name.png",
            "bad\x00name.png",
        ):
            with self.subTest(filename=filename):
                self.conn.read.reset_mock()
                result = await self.call_download(
                    model="res.partner",
                    record_id=7,
                    field="image",
                    filename=filename,
                )

                self.assertTrue(result.is_error)
                self.assertIn("filename", result.content[0].text.lower())
                self.conn.read.assert_not_awaited()

    async def test_does_not_escape_download_directory(self):
        result = await self.call_download(
            model="res.partner", record_id=7, field="image"
        )

        self.assertFalse(result.is_error)
        self.assertEqual(
            os.path.dirname(result.data["path"]), self.resolved_download_dir()
        )

    async def test_reports_missing_record(self):
        self.conn.read.return_value = []

        result = await self.call_download(
            model="res.partner", record_id=999, field="image"
        )

        self.assertTrue(result.is_error)
        self.assertIn("Record not found", result.content[0].text)

    async def test_reports_empty_field(self):
        self.conn.read.return_value = [{"image": False}]

        result = await self.call_download(
            model="res.partner", record_id=7, field="image"
        )

        self.assertTrue(result.is_error)
        self.assertIn("is empty", result.content[0].text)

    async def test_readonly_mode_still_blocks_save_binary_field(self):
        output_path = os.path.join(self.temp_dir.name, "saved.png")
        async with Client(self.app) as client:
            result = await client.call_tool(
                "save_binary_field",
                {
                    "model": "res.partner",
                    "record_id": 7,
                    "field": "image",
                    "output_path": output_path,
                },
                raise_on_error=False,
            )

        self.assertTrue(result.is_error)
        self.assertIn("READONLY_MODE", result.content[0].text)
        self.assertFalse(os.path.exists(output_path))
        self.conn.read.assert_not_awaited()
