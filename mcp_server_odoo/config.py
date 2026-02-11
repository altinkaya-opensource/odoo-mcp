"""Environment-based configuration for the MCP server."""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Configuration validation error."""


class OdooConfig:
    """Configuration loaded from environment variables."""

    def __init__(self):
        self.url = self._require("ODOO_URL").rstrip("/")
        self.db = self._require("ODOO_DB")
        self.username = self._require("ODOO_USER")
        self.password = self._require("ODOO_PASSWORD")

        self.readonly = os.getenv("READONLY_MODE", "").lower() in ("1", "true", "yes")
        self.log_level = os.getenv("ODOO_MCP_LOG_LEVEL", "INFO").upper()
        self.log_file = os.getenv("ODOO_MCP_LOG_FILE", "")
        self.default_limit = int(os.getenv("ODOO_MCP_DEFAULT_LIMIT", "10"))

    @staticmethod
    def _require(name):
        value = os.getenv(name)
        if not value:
            raise ConfigError(f"Missing required environment variable: {name}")
        return value


def setup_logging(config: OdooConfig) -> None:
    """Configure logging. Logs go to file or stderr (never stdout, reserved for MCP)."""
    level = getattr(logging, config.log_level, logging.INFO)
    handler = (
        logging.FileHandler(config.log_file)
        if config.log_file
        else logging.StreamHandler(sys.stderr)
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root = logging.getLogger("mcp_server_odoo")
    root.setLevel(level)
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("xmlrpc").setLevel(logging.WARNING)
