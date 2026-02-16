# 🔌 mcp-server-odoo

A [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI
assistants full access to your Odoo ERP instance over XML-RPC.

No Odoo module installation required. Just point it at any Odoo 12+ instance.

```
🤖 AI Assistant (Claude Code, Claude Desktop, etc.)
       │ MCP (stdio)
       ▼
  📡 mcp-server-odoo
       │ XML-RPC
       ▼
  🏢 Odoo Instance
```

## ⚡ Quick Start

No cloning required — just run directly from GitHub with [uv](https://docs.astral.sh/uv/):

### 🖥️ With Claude Code

```bash
claude mcp add odoo \
    -e ODOO_URL=http://localhost:8069 \
    -e ODOO_DB=mydb \
    -e ODOO_USER=admin \
    -e ODOO_PASSWORD=admin \
    -- uvx --from git+https://github.com/altinkaya-opensource/odoo-mcp mcp-server-odoo
```

### 🖱️ With Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/altinkaya-opensource/odoo-mcp",
        "mcp-server-odoo"
      ],
      "env": {
        "ODOO_URL": "http://localhost:8069",
        "ODOO_DB": "mydb",
        "ODOO_USER": "admin",
        "ODOO_PASSWORD": "admin"
      }
    }
  }
}
```

### 🔒 Readonly Mode

Block all write operations by adding `READONLY_MODE=true`:

```bash
claude mcp add odoo \
    -e ODOO_URL=http://localhost:8069 \
    -e ODOO_DB=mydb \
    -e ODOO_USER=admin \
    -e ODOO_PASSWORD=admin \
    -e READONLY_MODE=true \
    -- uvx --from git+https://github.com/altinkaya-opensource/odoo-mcp mcp-server-odoo
```

## 🛠️ Tools

### 📖 Read Operations

| Tool               | Description                                                                       |
| ------------------ | --------------------------------------------------------------------------------- |
| `search_records`   | 🔍 Search any model with domain filters, field selection, pagination, and sorting |
| `read_record`      | 📄 Read a single record by ID with smart field selection                          |
| `get_record_count` | 🔢 Count records matching a domain filter (lightweight, no data fetched)          |
| `list_models`      | 📋 List all non-transient models available in the database                        |
| `get_model_fields` | 🏗️ Inspect field definitions (type, required, help text, etc.) for any model      |

### ✏️ Write Operations

| Tool             | Description                                                                           |
| ---------------- | ------------------------------------------------------------------------------------- |
| `create_record`  | ➕ Create a new record in any model                                                   |
| `update_record`  | 📝 Update fields on an existing record                                                |
| `delete_record`  | 🗑️ Delete a record by ID                                                              |
| `execute_method` | ⚙️ Call any business method (e.g. `action_confirm`, `button_validate`, `action_post`) |

> 🚫 Write tools are disabled when `READONLY_MODE=true`.

## ✨ Features

### 🧠 Smart Field Selection

When you don't specify which fields to fetch, the server automatically picks the most
useful ones. It scores fields based on type, importance patterns (`state`, `amount`,
`partner`, etc.), and excludes noisy fields like `message_ids`, binary blobs, and
computed non-stored fields. You always get `id`, `name`, `display_name`, and `active`.

Pass `fields=["__all__"]` to override and get everything.

### 🔄 Flexible Domain Parsing

Domains can be passed as JSON strings, Python repr strings, or native lists:

```python
# All of these work:
[["is_company", "=", true]]
'[["is_company", "=", true]]'
"[('is_company', '=', True)]"
```

### 📅 ISO 8601 Dates

Odoo's `"2025-06-07 21:55:52"` datetime strings are automatically converted to
`"2025-06-07T21:55:52+00:00"` for standard ISO 8601 output.

## 💡 Tool Usage Examples

**🔍 Search for Turkish companies:**

```
search_records("res.partner", [["is_company", "=", true], ["country_id.code", "=", "TR"]], limit=20)
```

**🔢 Count open sale orders:**

```
get_record_count("sale.order", [["state", "=", "sale"]])
```

**📄 Read a specific product with all fields:**

```
read_record("product.product", 42, fields=["__all__"])
```

**✅ Confirm a sale order:**

```
execute_method("sale.order", "action_confirm", [42])
```

**📦 Validate a stock picking:**

```
execute_method("stock.picking", "button_validate", [15])
```

**💰 Post an invoice:**

```
execute_method("account.move", "action_post", [100])
```

**🏗️ Discover fields on a model:**

```
get_model_fields("sale.order", attributes=["string", "type", "required"])
```

## ⚙️ Configuration

All configuration is done through environment variables:

| Variable                 | Required | Default | Description                                     |
| ------------------------ | -------- | ------- | ----------------------------------------------- |
| `ODOO_URL`               | ✅       |         | Odoo server URL (e.g. `http://localhost:8069`)  |
| `ODOO_DB`                | ✅       |         | Database name                                   |
| `ODOO_USER`              | ✅       |         | Username                                        |
| `ODOO_PASSWORD`          | ✅       |         | Password or API key                             |
| `READONLY_MODE`          |          | `false` | Set to `true` to disable all write operations   |
| `ODOO_MCP_LOG_LEVEL`     |          | `INFO`  | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ODOO_MCP_LOG_FILE`      |          | stderr  | Path to log file                                |
| `ODOO_MCP_DEFAULT_LIMIT` |          | `10`    | Default record limit for search operations      |

Alternatively, create a `.env` file in the project root.

## 📋 Requirements

- 🐍 Python >= 3.10
- 📦 [uv](https://docs.astral.sh/uv/) (recommended) or pip
- 🏢 Access to an Odoo instance (12.0+) with XML-RPC enabled

## 📜 License

AGPL-3.0-or-later
