"""Entry point: python -m mcp_server_odoo"""

from .server import create_server

app = create_server()
app.run()
