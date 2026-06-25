# ADT MCP (Python)

Multi-system MCP server for reading and writing ABAP source via SAP ADT,
with a local web admin to configure systems. One process serves both the
MCP endpoint (`/mcp`) and the web admin (`/`).

## Install

```bash
cd adt-mcp
python -m pip install -e .
# dev/test deps:
python -m pip install -r requirements.txt
```

## Run

```bash
python -m adt_mcp        # or: adt-mcp
# → http://127.0.0.1:8765  (MCP at /mcp, admin at /)
```

Open http://127.0.0.1:8765 to add SAP systems (URL, client, language, auth).
Config is stored in `systems.json` (gitignored). See `systems.example.json`.
Cookie systems can be (re)authenticated from the web admin via a browser login.

## Connect Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "sap-adt": { "type": "http", "url": "http://127.0.0.1:8765/mcp" }
  }
}
```

## Tools

Read / navigate:
- `list_systems`, `list_package`, `search_objects`
- `get_source`, `get_source_by_uri`, `get_class_method_source`,
  `get_class_include`, `get_object_structure`, `get_package_source`
- `grep_package`, `find_references` (where-used), `cds_dependencies`
- `get_context` (object + compressed dependencies: CDS/BDEF/CLAS)
- `get_revisions`, `get_revision_source`, `compare_source`
- `syntax_check`, `run_unit_tests` (ABAP Unit), `data_preview` (CDS/SQL data)
- `trace_start`, `trace_list`, `trace_analyze` (ABAP profiler: CPU hotspots + DB accesses)
- `list_dumps`, `get_dump` (ST22 runtime dumps: liệt kê + đọc chi tiết để phân tích lỗi)

Write (gated by safety, see below):
- `update_source`, `update_class_include`, `activate`
- `create_object` (CLAS / INTF / DDLS / DDLX / BDEF / SRVD / SRVB / TABL)
- `clone_package` (clone toàn bộ object của một package sang package đích, thêm suffix `_VN` + sửa tham chiếu chéo trong source; dry-run mặc định)

Cookie maintenance: `refresh_cookies_for`.

## Write safety

Writes are **off by default**. Per system in `systems.json`:
- `allow_write: true` — required to enable any create/update.
- `write_packages: ["Z*", "$TMP"]` — target package must match (default).

Delete is intentionally **not** supported.

## Token economy

Tool schemas are sent to the model on every turn. Set `ADT_MCP_TOOLS=core`
to expose only the essential ~16 tools (smaller schema); default `full`
exposes all 29. Descriptions are kept terse.

```bash
ADT_MCP_TOOLS=core python -m adt_mcp
```

## Test

```bash
python -m pytest -v
```

## Security

- `systems.json`, `cookies/`, `*-cookies.txt` hold session secrets and are
  gitignored — never commit them.
- The server binds `127.0.0.1` only.
- **Stored passwords are plaintext.** A `username`/`password` is only kept to
  enable headless cookie refresh (`refresh_cookies_for`). For real systems
  prefer the cookie flows that store **no** password:
  - `mode: "browser"` — log in once in a visible browser; only session cookies
    are saved (the persistent profile keeps SSO so re-login is rare).
  - `mode: "cdp"` — attach to your already-authenticated Chrome.
  If you must keep a password, store it in an OS keyring / secrets manager and
  inject it into `systems.json` at deploy time rather than committing it.
