"""Tests for environment-based configuration."""

import os
import unittest
from unittest.mock import patch

from mcp_server_odoo.config import OdooConfig


class TestDownloadDirectoryConfig(unittest.TestCase):
    def setUp(self):
        self.required_env = {
            "ODOO_URL": "https://example.com",
            "ODOO_DB": "test",
            "ODOO_USER": "user",
            "ODOO_PASSWORD": "secret",
        }

    def test_default_download_dir(self):
        expected = os.path.expanduser("~/.cache/odoo-mcp")

        with patch.dict(os.environ, self.required_env, clear=False):
            os.environ.pop("ODOO_MCP_DOWNLOAD_DIR", None)
            config = OdooConfig()

        self.assertEqual(config.download_dir, expected)

    def test_empty_download_dir_uses_default(self):
        expected = os.path.expanduser("~/.cache/odoo-mcp")

        with patch.dict(
            os.environ,
            {**self.required_env, "ODOO_MCP_DOWNLOAD_DIR": ""},
            clear=False,
        ):
            config = OdooConfig()

        self.assertEqual(config.download_dir, expected)

    def test_download_dir_can_be_overridden(self):
        expected = os.path.expanduser("~/custom-downloads")

        with patch.dict(
            os.environ,
            {
                **self.required_env,
                "ODOO_MCP_DOWNLOAD_DIR": "~/custom-downloads",
            },
            clear=False,
        ):
            config = OdooConfig()

        self.assertEqual(config.download_dir, expected)
