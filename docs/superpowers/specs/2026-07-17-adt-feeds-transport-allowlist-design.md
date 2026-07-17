# ADT MCP: Feeds Reader, Transport Assignment, Allow-List Guardrail

Date: 2026-07-17
Status: Approved

## Context

SAP is shipping an official **ADT MCP Server** (roadmap 2611 → 2702) with new
MCP tools. Comparing that tool list to our `sap-adt` server, three
newly-announced capabilities are not yet covered. All three were verified
against a live system (IPS = my405871, S/4HANA Cloud Public) by hitting the
underlying ADT REST endpoints directly:

| Capability | ADT endpoint | IPS probe result | Decision |
|---|---|---|---|
| Read ABAP feeds | `/sap/bc/adt/feeds` | HTTP 200 — catalog lists *ABAP Runtime Errors*, *SAP Gateway Error Log*, *ABAP System Messages*, ATC Findings, Contract Check Violations, System Monitoring | Build |
| Assign to transport | `/sap/bc/adt/cts/transportrequests` (accept `…transportorganizertree.v1+xml`) | HTTP 200 — returned a real transport request | Build |
| Source code search | `/sap/bc/adt/repository/informationsystem/textsearch` | HTTP 500 "Source Search is not supported" (planned 2702) | Deferred — keep `grep_package` |
| Allow-list guardrail | none (server-side config) | n/a | Build |

The `sap-adt` server calls ADT REST endpoints directly, so feeds and transport
work now — no need to wait for SAP's packaged 2702 release.

## Goals

Add three independent capabilities without changing existing tools:

1. **ABAP feeds reader** — gateway error log, system messages, and other ADT
   feeds (dumps already covered by `list_dumps`/`get_dump`, kept as-is).
2. **Transport assignment** — list open transports and create a new one, so an
   agent can obtain a transport number to pass to the existing write tools.
3. **Allow-list guardrail** — restrict which object names write tools may touch,
   extending the existing package-level `check_write` gate.

Non-goals: source code snippet search (backend unsupported on target release);
reassigning an already-transported object to a different request (rare — v2).

## Design

### A. ABAP Feeds Reader

Endpoint: `GET /sap/bc/adt/feeds` returns an atom catalog of available feeds;
each entry carries a query href. Reading a feed GETs that href with optional
filters (from/to/user/object).

`adt_client.py`:
- `FEED_ALIASES: dict[str, str]` — friendly key → feed title in the catalog
  (`gateway_log` → "SAP Gateway Error Log", `system_messages` → "ABAP System
  Messages", `dumps` → "ABAP Runtime Errors", `system_monitoring`,
  `atc_findings`, `contract_violations`).
- `parse_feed_catalog(data) -> list[dict]` — `{title, href}` per catalog entry.
- `parse_feed_entries(data) -> list[dict]` — generic atom-entry parse
  (`{title, author, date, uri, summary, categories}`), modelled on
  `parse_dumps_feed`.
- `ADTClient.list_feeds(system) -> str` — GET catalog, list `{alias?, title,
  href}`.
- `ADTClient.read_feed(system, feed, from_date, to_date, user, object, max)`
  — resolve the feed href from the catalog (accept alias or exact title),
  GET with query filters, format entries newest-first.

`server.py` tools:
- `list_feeds(system)`.
- `read_feed(system, feed, from_date=None, to_date=None, user=None, object=None, max=50)`.

### B. Transport Assignment

Endpoint: `GET /sap/bc/adt/cts/transportrequests` with accept
`application/vnd.sap.adt.transportorganizertree.v1+xml` (verified 200); `POST`
to create a workbench request.

`adt_client.py`:
- `parse_transports(data) -> list[dict]` — `{number, description, status,
  owner, type}` for the user's modifiable requests.
- `ADTClient.list_transports(system) -> str`.
- `ADTClient.create_transport(system, description) -> str` — POST a new
  workbench request, return `OK: created <TR> <desc>` or an error.

`server.py` tools:
- `list_transports(system)`.
- `create_transport(system, description)`.

Object assignment itself already works: `create_object` / `update_source` /
`update_class_include` accept a `transport` argument passed as `corrNr`. The
agent flow is: list or create a transport, then pass its number to a write tool.

### C. Allow-List Guardrail

`registry.py`:
- Add `write_objects: list[str] | None = None` to `System` (parallel to
  `write_packages`), read in `from_dict` / serialized in `to_dict`.

`adt_client.py`:
- Extend `check_write(system, package, object_name="")`: when
  `system.write_objects` is set, `object_name` must match at least one pattern
  (`fnmatch`, case-insensitive); otherwise reject before execution. When
  `write_objects` is `None` the behaviour is unchanged (no breaking change).
- Update call sites (`update_source`, `update_class_include`, `create_object`,
  `clone_package`) to pass the object name.

Configuration lives in `systems.json`, mirroring `write_packages`. Default
`None` keeps existing systems unrestricted.

## Testing (TDD)

Pure unit tests, no live SAP, following `tests/test_write.py`:
- `parse_feed_catalog`, `parse_feed_entries` against sample atom payloads.
- `read_feed` alias resolution + filter query building (mock transport).
- `parse_transports` against a sample organizer-tree payload;
  `create_transport` POST body/URL (mock transport).
- `check_write` with `write_objects`: allowed match, rejected non-match, and
  `None` = unrestricted.

## Rollout

- No existing tool changes; five new tools added.
- Allow-list defaults off — no behavioural change until configured.
- Feeds and transport usable immediately on IPS.
