"""FastMCP server setup and lifecycle."""

import logging

from mcp.server.fastmcp import FastMCP

from .config import OdooConfig, setup_logging
from .connection import OdooConnection
from .tools import register_tools

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Build and return a configured FastMCP server instance."""
    config = OdooConfig()
    setup_logging(config)

    app = FastMCP(
        "odoo-mcp",
        instructions="MCP server for Odoo ERP integration",
    )

    conn = OdooConnection(config)
    conn.connect()

    mode = "READONLY" if config.readonly else "FULL ACCESS"
    logger.info("MCP server mode: %s", mode)

    register_tools(app, conn, config)
    logger.info("MCP server ready with 9 tools")

    return app
