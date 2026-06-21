---
name: sap-abap-adt
description: Use when reading or writing ABAP on an SAP system via the sap-adt MCP — ABAP classes, CDS (DDLS), RAP behavior (BDEF/behavior pool), service definition/binding (SRVD/SRVB), tables; exploring packages, checking syntax, running ABAP Unit, previewing CDS/SQL data, where-used, version diffs, or profiling why ABAP/CDS/RAP is slow. ABAP Cloud / S/4HANA Public Cloud.
---

# SAP ABAP via the sap-adt MCP

Drive a SAP system over ADT through the `sap-adt` MCP server. Tools are exposed
as `mcp__sap-adt__<tool>`. Every tool takes a `system` argument.

## Always first
1. `list_systems` → get the exact system name (e.g. `sap-vnext`). **Every** tool
   needs `system`; an unknown name returns a clear error listing valid ones.
2. If a call returns **"session expired … refresh cookies"** → call
   `refresh_cookies_for(system)` once, then retry. It runs a **headless login
   with the system's stored username/password** (offloaded to a worker thread,
   so it no longer crashes with *"Playwright Sync API inside the asyncio loop"*).
   It works **only** when credentials are stored; a cookie/browser-login system
   with no stored password returns *"needs username and password"* → the user
   must re-login from the web admin instead (its refresh can open an interactive
   browser, which needs a desktop — on a headless service host, do it over RDP:
   `Stop-Service adt-mcp` → run foreground → browser login → `Start-Service`).

## Object type codes
`CLAS` class · `INTF` interface · `PROG` program · `INCL` include · `FUGR`
function group (needs `function_group`) · `DDLS` CDS/DDL source · `DDLX`
metadata extension · `BDEF` RAP behavior definition · `SRVD` service definition
· `SRVB` service binding · `TABL` table · `VIEW`/`STRU` view/structure.

## Tool catalog

**Read / navigate**
| tool | use |
|---|---|
| `get_source(object_type,name[,function_group])` | full source of one object |
| `get_source_by_uri(uri)` | source from a uri returned by list/search |
| `get_class_method_source(class_name,method)` | one METHOD…ENDMETHOD block |
| `get_class_include(class_name,include)` | class include: definitions \| implementations \| macros \| testclasses |
| `get_object_structure(class_name)` | method-name outline of a class |
| `list_package(package[,recursive])` | objects + subpackages in a package |
| `search_objects(query[,max_results])` | name/wildcard search e.g. `ZCL_ORDER*` |
| `get_package_source(package[,max_objects])` | concatenated source of a package |
| `grep_package(package,pattern[,ignore_case,max_objects])` | regex over a package's source |

**Understand / intelligence**
| tool | use |
|---|---|
| `get_context(object_type,name[,depth])` | **one-call big picture**: DDLS→CDS deps; BDEF→behavior-for CDS + impl class; CLAS→superclass + interfaces (custom expanded, standard listed) |
| `find_references(object_uri[,line,column])` | where-used (downstream) |
| `cds_dependencies(ddls_name)` | upstream FROM/JOIN/ASSOCIATION/COMPOSITION of a CDS |
| `api_release_state(object_type,name[,function_group])` | released for ABAP Cloud? (Clean Core contracts) |

**History**
| `get_revisions(object_type,name[,function_group,include])` · `get_revision_source(version_uri)` · `compare_source(object_type,name,version_uri[,against,function_group])` (unified diff) |

**Quality / runtime**
| tool | use |
|---|---|
| `syntax_check(object_type,name[,function_group,version,source])` | syntax/check-run; pass `source` to check unsaved code |
| `run_unit_tests(object_type,name)` | ABAP Unit (CLAS/PROG/FUGR); "No ABAP Unit tests found" = the object has no test classes |
| `data_preview(query[,max_rows])` | preview a CDS entity or run an Open SQL SELECT |
| `pretty_print(source)` | format ABAP to the system's style |

**Performance profiling** (see recipe below)
| `trace_start(process_type[,max_executions,expires_minutes,title])` · `trace_list([max_runs])` · `trace_analyze(trace_uri[,top])` |

**Write** (gated — see Write safety)
| `update_source(object_type,name,source[,transport,function_group,activate])` · `update_class_include(class_name,include,source[,transport,activate])` · `activate(object_type,name[,function_group])` · `create_object(object_type,name,package[,description,source,transport,service_definition,binding_version])` |

## Gotchas (non-obvious, verified)
- **`data_preview` column names = CDS element names** (as shown in the result
  header, e.g. `SalesOrder`, `MaxScheduleLine`), **not** the underlying table
  field names with underscores. A bare entity name auto-wraps to
  `SELECT * FROM <name>`; pass a full `SELECT … WHERE …` to filter. Keep leading
  zeros as strings (`'0000000085'`).
- **`data_preview` on draft/projection consumption views can 500** — query the
  interface view instead. Auth-restricted tables return "No authorization".
- **`get_context` is the fastest way to understand a RAP BO** — call it on the
  BDEF to pull the behavior-for CDS (+ its deps) and the behavior pool class in
  one shot.
- **`trace_*` captures *all* HTTP the user does in the window** — run the
  workload in isolation so the trace is clean. `process_type=http` covers
  Fiori/OData and `data_preview`; use `dialog`/`batch` otherwise.
- **`trace_list` time columns are total / ABAP / DB ms** — a high DB share means
  DB-bound; then read the DB accesses in `trace_analyze` for redundant/expensive
  SELECTs (watch `count` and `buffered`).
- **No delete** — the MCP intentionally cannot delete objects.

## Write safety
Writes need the system's `allow_write: true` **and** the target package to match
its `write_packages` (default `Z*`, `$TMP`). The gate reads the object's real
package, not your argument. Transportable packages need a `transport`.
Before activating, prefer `syntax_check(..., source=<new code>)` to catch errors.

## Recipes

**Understand an object**: `get_context(...)` first; drill in with
`get_source` / `get_class_method_source`; map impact with `find_references`.

**Edit + activate safely** (RAP logic lives in the behavior pool class
implementations include):
1. `get_source` / `get_class_include` to read current code.
2. `syntax_check(object_type,name,source=<new>)`.
3. `update_source(...)` or `update_class_include(class_name,"implementations",source)`
   (`activate=True` activates; use `False` to batch then `activate(...)`).

**Scaffold a RAP stack**: `create_object` for `TABL` → `DDLS` (interface +
projection) → `DDLX` → `BDEF` → behavior pool `CLAS` → `SRVD` → `SRVB`
(`SRVB` needs `service_definition`), passing `source` where applicable.

**Verify behavior**: `run_unit_tests(CLAS, <test class>)`; inspect data with
`data_preview`.

**Find why something is slow**:
1. `trace_start(process_type="http")`.
2. Run the slow workload (Fiori/OData action, or trigger via `data_preview`).
3. `trace_list` → pick the run's `uri` (check the DB-ms share).
4. `trace_analyze(uri)` → top time consumers + DB access table.

## Common mistakes
- Forgetting `system` / using a name not in `list_systems`.
- Filtering `data_preview` with table field names (underscores) → "Unknown
  column name". Use the CDS element names.
- Expecting `run_unit_tests` to find tests that don't exist (empty result is
  correct, not an error).
- Writing to a package outside `write_packages`, or on a system without
  `allow_write` → blocked by the safety gate (expected).
- Re-running the server and not seeing new tools in the client → reconnect the
  MCP (tool list is cached at connect time).
