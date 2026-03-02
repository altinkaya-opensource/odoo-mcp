"""FastMCP server setup and lifecycle."""

import logging

from fastmcp import FastMCP

from .config import OdooConfig, setup_logging
from .connection import OdooConnection
from .tools import register_tools

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """\
MCP server for Odoo ERP integration via XML-RPC.

## Odoo Domain Syntax (used for filtering records)
A domain is a list of conditions (leaves). Each leaf is a list of 3 elements:
  [field_name, operator, value]

### Operators
=, !=, <, >, <=, >=, like, ilike (case-insensitive contains),
not like, not ilike, =like, =ilike, in, not in, child_of, parent_of

### Combining Conditions
- Multiple leaves are implicitly ANDed: [[A], [B]] means A AND B
- OR requires the '|' prefix operator: ['|', [A], [B]] means A OR B
- NOT uses '!' prefix: ['!', [A]] means NOT A
- '&' and '|' are BINARY (consume exactly 2 operands after them)
- '!' is UNARY (consumes exactly 1 operand after it)
- For 3+ OR conditions, chain '|': ['|', [A], '|', [B], [C]]
- (A AND B) OR (C AND D): ['|', '&', [A], [B], '&', [C], [D]]

### Dot Notation
Traverse relations with dots: 'partner_id.country_id.code', 'order_line.product_id.name'

### Examples
  []                                          -- all records
  [["is_company", "=", true]]                 -- companies only
  [["state", "=", "sale"]]                    -- confirmed sale orders
  [["state", "in", ["draft", "sent"]]]        -- draft or sent
  ["|", ["email", "ilike", "@gmail"], ["email", "ilike", "@yahoo"]]
  [["partner_id.country_id.code", "=", "TR"]] -- Turkish partners

### Common Models
res.partner, sale.order, sale.order.line, purchase.order, purchase.order.line,
account.move, account.move.line, product.product, product.template,
stock.picking, stock.move, stock.quant, mrp.production, project.task,
hr.employee, crm.lead
"""


def create_server() -> FastMCP:
    """Build and return a configured FastMCP server instance."""
    config = OdooConfig()
    setup_logging(config)

    app = FastMCP(
        "odoo-mcp",
        instructions=SERVER_INSTRUCTIONS,
    )

    conn = OdooConnection(config)
    conn.connect()

    mode = "READONLY" if config.readonly else "FULL ACCESS"
    logger.info("MCP server mode: %s", mode)

    register_tools(app, conn, config)
    logger.info("MCP server ready with 11 tools")

    return app
