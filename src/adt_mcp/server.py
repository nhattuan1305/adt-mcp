"""FastMCP server wiring registry + ADT client into MCP tools."""
import os
import anyio
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, PlainTextResponse
from .registry import System, SystemRegistry
from .adt_client import ADTClient
from .cookie_refresh import refresh_cookies, interactive_login, cdp_capture


def _cookies_dir() -> str:
    d = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cookies")
    os.makedirs(d, exist_ok=True)
    return d


def format_systems(systems: list[System]) -> str:
    if not systems:
        return "No systems configured. Open the web admin to add one."
    lines = ["Available systems:"]
    for s in systems:
        lines.append(f"- {s.name}: {s.url} (client {s.client}, auth {s.auth})")
    return "\n".join(lines)


def resolve_and_get(registry: SystemRegistry, adt: ADTClient,
                    system: str, object_type: str, name: str,
                    function_group: str | None) -> str:
    try:
        sys = registry.get(system)
    except KeyError:
        names = ", ".join(s.name for s in registry.list()) or "(none)"
        return f"Error: unknown system {system!r}. Known: {names}"
    return adt.get_source(sys, object_type, name, function_group)


def resolve_and_refresh(registry: SystemRegistry, system: str) -> str:
    """Refresh a cookie system's session via SAML login (Playwright)."""
    try:
        sys = registry.get(system)
    except KeyError:
        names = ", ".join(s.name for s in registry.list()) or "(none)"
        return f"Error: unknown system {system!r}. Known: {names}"
    if sys.auth != "cookie" or not sys.cookie_file:
        return (f"Error: system {system!r} is not a cookie_file system; "
                f"refresh only applies to cookie auth with a cookie_file")
    if not sys.username or not sys.password:
        return (f"Error: system {system!r} needs username and password "
                f"(stored for login) to refresh cookies")
    return refresh_cookies(sys.url, sys.username, sys.password, sys.cookie_file)


def build_server(registry: SystemRegistry, adt: ADTClient) -> FastMCP:
    mcp = FastMCP("adt-mcp", host="127.0.0.1")
    mcp.registry = registry  # type: ignore[attr-defined]
    mcp.adt = adt            # type: ignore[attr-defined]

    @mcp.tool()
    def list_systems() -> str:
        """List configured SAP systems available for source retrieval."""
        return format_systems(registry.list())

    @mcp.tool()
    def get_source(system: str, object_type: str, name: str,
                   function_group: str | None = None) -> str:
        """Fetch ABAP source from a configured SAP system.

        object_type: CLAS | PROG | INTF | INCL | FUGR.
        function_group is required when object_type is FUGR.
        """
        return resolve_and_get(registry, adt, system, object_type,
                               name, function_group)

    def _resolve(system: str):
        """Return (System, None) or (None, error_text)."""
        try:
            return registry.get(system), None
        except KeyError:
            names = ", ".join(s.name for s in registry.list()) or "(none)"
            return None, f"Error: unknown system {system!r}. Known: {names}"

    def _fmt_objects(objs) -> str:
        if isinstance(objs, str):
            return objs
        if not objs:
            return "(none)"
        lines = []
        for o in objs:
            desc = f" — {o['description']}" if o.get("description") else ""
            lines.append(f"{o['type']:<10} {o['name']}{desc}\t[{o['uri']}]")
        return "\n".join(lines)

    @mcp.tool()
    def list_package(system: str, package: str, recursive: bool = False) -> str:
        """List objects and subpackages inside an ABAP package.

        Returns one object per line: TYPE NAME — description [uri].
        Set recursive=true to descend into subpackages.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return _fmt_objects(adt.list_package(sys, package, recursive))

    @mcp.tool()
    def search_objects(system: str, query: str, max_results: int = 20) -> str:
        """Search ABAP objects by name/wildcard (e.g. 'ZCL_ORDER*')."""
        sys, err = _resolve(system)
        if err:
            return err
        return _fmt_objects(adt.search_objects(sys, query, max_results))

    @mcp.tool()
    def get_source_by_uri(system: str, uri: str) -> str:
        """Fetch ABAP source for an object by its ADT URI (from list/search)."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_source_by_uri(sys, uri)

    @mcp.tool()
    def get_class_method_source(system: str, class_name: str,
                                method: str) -> str:
        """Fetch a single METHOD…ENDMETHOD block from a class."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_class_method_source(sys, class_name, method)

    @mcp.tool()
    def get_class_include(system: str, class_name: str, include: str) -> str:
        """Fetch a class include: definitions | implementations | macros | testclasses."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_class_include(sys, class_name, include)

    @mcp.tool()
    def get_object_structure(system: str, class_name: str) -> str:
        """List the declared method names of a class (outline)."""
        sys, err = _resolve(system)
        if err:
            return err
        res = adt.object_structure(sys, class_name)
        if isinstance(res, str):
            return res
        return "\n".join(res) if res else "(no methods declared)"

    @mcp.tool()
    def get_package_source(system: str, package: str,
                           max_objects: int = 50) -> str:
        """Concatenated source of all source-bearing objects in a package."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_package_source(sys, package, max_objects)

    @mcp.tool()
    def grep_package(system: str, package: str, pattern: str,
                     ignore_case: bool = False, max_objects: int = 100) -> str:
        """Regex-search the source of objects in a package.

        Returns matches as NAME:line: text.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return adt.grep_package(sys, package, pattern, ignore_case, max_objects)

    @mcp.tool()
    def get_revisions(system: str, object_type: str, name: str,
                      function_group: str | None = None,
                      include: str | None = None) -> str:
        """List version history of an object (PROG/CLAS/INTF/FUNC/INCL/DDLS/BDEF/SRVD).

        Returns one version per line: date  author  version  [transport]  uri.
        For CLAS pass include (main/definitions/implementations/...) if needed;
        for FUNC pass function_group.
        """
        sys, err = _resolve(system)
        if err:
            return err
        res = adt.get_revisions(sys, object_type, name, function_group, include)
        if isinstance(res, str):
            return res
        if not res:
            return "(no revisions)"
        lines = []
        for r in res:
            tr = f"  TR={r['transport']}" if r.get("transport") else ""
            lines.append(f"{r['date']}  {r['author']}  {r['title'] or r['version']}"
                         f"{tr}\t[{r['uri']}]")
        return "\n".join(lines)

    @mcp.tool()
    def get_revision_source(system: str, version_uri: str) -> str:
        """Fetch source of a specific past version (uri from get_revisions)."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_revision_source(sys, version_uri)

    @mcp.tool()
    def compare_source(system: str, object_type: str, name: str,
                       version_uri: str, against: str = "current",
                       function_group: str | None = None) -> str:
        """Unified diff between a past version and another version (default: current)."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.compare_source(sys, object_type, name, version_uri,
                                  against, function_group)

    @mcp.tool()
    def find_references(system: str, object_uri: str, line: int = 0,
                        column: int = 0) -> str:
        """Where-used: find objects that use the given object (or symbol).

        object_uri comes from list_package/search_objects. Optionally pass
        line+column to find references to a specific symbol at that position.
        Returns one user per line: TYPE NAME (package) [uri].
        """
        sys, err = _resolve(system)
        if err:
            return err
        res = adt.find_references(sys, object_uri, line, column)
        if isinstance(res, str):
            return res
        if not res:
            return "(no references found)"
        lines = []
        for r in res:
            pkg = f" ({r['package']})" if r.get("package") else ""
            lines.append(f"{r['type']:<10} {r['name']}{pkg}\t[{r['uri']}]")
        return "\n".join(lines)

    @mcp.tool()
    def cds_dependencies(system: str, ddls_name: str) -> str:
        """Upstream dependencies of a CDS view (FROM / JOIN / ASSOCIATION / COMPOSITION).

        Parsed from the CDS source, so it works on cloud. For downstream impact
        (who uses this view) use find_references on the view's URI.
        """
        sys, err = _resolve(system)
        if err:
            return err
        res = adt.cds_dependencies(sys, ddls_name)
        if isinstance(res, str):
            return res
        if not res:
            return "(no dependencies found)"
        return "\n".join(f"{r['relation']:<12} {r['name']}" for r in res)

    @mcp.tool()
    def get_context(system: str, object_type: str, name: str,
                    depth: int = 1) -> str:
        """Bundle an object's full source + its compressed dependencies.

        For CDS (DDLS) it recurses through FROM/ASSOCIATION/COMPOSITION up to
        `depth`, expanding custom (Z*) views/tables (compressed) and listing
        standard SAP objects. One call instead of many get_source calls.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return adt.get_context(sys, object_type, name, depth)

    @mcp.tool()
    def update_source(system: str, object_type: str, name: str, source: str,
                      transport: str | None = None,
                      function_group: str | None = None,
                      activate: bool = True) -> str:
        """Edit an existing object's source, then activate (write — requires allow_write).

        object_type: CLAS/PROG/INTF/INCL/DDLS/DDLX/BDEF/SRVD/TABL/VIEW/STRU/FUGR.
        Pass activate=False to defer activation when writing several parts.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return adt.update_source(sys, object_type, name, source, transport,
                                 function_group, activate)

    @mcp.tool()
    def update_class_include(system: str, class_name: str, include: str,
                             source: str, transport: str | None = None,
                             activate: bool = True) -> str:
        """Edit a class include: main / definitions / implementations / macros / testclasses.

        RAP behavior logic lives in 'implementations' (local lhc_*/lsc_* classes).
        Use activate=False to write several includes, then call activate once.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return adt.update_class_include(sys, class_name, include, source,
                                        transport, activate)

    @mcp.tool()
    def activate(system: str, object_type: str, name: str,
                 function_group: str | None = None) -> str:
        """Activate an object (write — requires allow_write)."""
        sys, err = _resolve(system)
        if err:
            return err
        return adt.activate(sys, object_type, name, function_group)

    @mcp.tool()
    def create_object(system: str, object_type: str, name: str, package: str,
                      description: str = "", source: str | None = None,
                      transport: str | None = None,
                      service_definition: str | None = None,
                      binding_version: str = "V2") -> str:
        """Create a new RAP object (write — requires allow_write).

        Types: CLAS/PROG/INTF/DDLS/DDLX/BDEF/SRVD/SRVB/TABL. package must exist;
        transport required for transportable packages (omit for local $). If
        source is given (source types), it is written and activated. SRVB needs
        service_definition.
        """
        sys, err = _resolve(system)
        if err:
            return err
        return adt.create_object(sys, object_type, name, package, description,
                                 source, transport, service_definition,
                                 binding_version)

    @mcp.tool()
    def refresh_cookies_for(system: str) -> str:
        """Refresh expired SAML session cookies for a cookie_file system.

        Performs a headless browser login using the system's stored
        username/password and rewrites its cookie file. Use when get_source
        reports the session expired.
        """
        return resolve_and_refresh(registry, system)

    web_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web")

    @mcp.custom_route("/", methods=["GET"])
    async def index(request: Request) -> HTMLResponse:
        path = os.path.join(web_dir, "index.html")
        if not os.path.exists(path):
            return PlainTextResponse("web/index.html missing", status_code=500)
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @mcp.custom_route("/api/systems", methods=["GET"])
    async def api_list(request: Request) -> JSONResponse:
        systems = [
            {"name": s.name, "url": s.url, "client": s.client,
             "language": s.language, "auth": s.auth}
            for s in registry.list()
        ]
        return JSONResponse({"systems": systems})

    @mcp.custom_route("/api/systems", methods=["POST"])
    async def api_upsert(request: Request) -> JSONResponse:
        body = await request.json()
        sys = System(
            name=body["name"], url=body["url"],
            client=body.get("client", "001"),
            language=body.get("language", "EN"),
            auth=body.get("auth", "basic"),
            username=body.get("username"), password=body.get("password"),
            cookie_file=body.get("cookie_file"),
            cookie_string=body.get("cookie_string"))
        registry.upsert(sys)
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/systems/{name}", methods=["DELETE"])
    async def api_delete(request: Request) -> JSONResponse:
        registry.delete(request.path_params["name"])
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/systems/{name}/test", methods=["POST"])
    async def api_test(request: Request) -> JSONResponse:
        try:
            sys = registry.get(request.path_params["name"])
        except KeyError:
            return JSONResponse({"result": "Error: unknown system"})
        result = await anyio.to_thread.run_sync(adt.test_connection, sys)
        return JSONResponse({"result": result})

    @mcp.custom_route("/api/systems/login", methods=["POST"])
    async def api_login(request: Request) -> JSONResponse:
        """Create a cookie system by logging in and capturing cookies.

        Body: {name, url, client?, language?, mode: "browser"|"headless",
               username?, password?}. mode=browser opens a visible IAS login
               (no password stored); mode=headless logs in with credentials.
        """
        body = await request.json()
        name = (body.get("name") or "").strip()
        url = (body.get("url") or "").strip()
        if not name or not url:
            return JSONResponse({"result": "Error: name and url are required"})
        mode = body.get("mode", "browser")
        cookie_file = os.path.join(_cookies_dir(), f"{name}.txt")

        if mode == "headless":
            user = (body.get("username") or "").strip()
            pw = body.get("password") or ""
            if not user or not pw:
                return JSONResponse({"result":
                    "Error: headless mode requires username and password"})
            result = await anyio.to_thread.run_sync(
                refresh_cookies, url, user, pw, cookie_file)
        elif mode == "cdp":
            cdp_url = os.environ.get("ADT_MCP_CDP", "http://127.0.0.1:9222")
            result = await anyio.to_thread.run_sync(
                cdp_capture, url, cookie_file, cdp_url)
        else:
            result = await anyio.to_thread.run_sync(
                interactive_login, url, cookie_file)

        if result.startswith("OK"):
            registry.upsert(System(
                name=name, url=url,
                client=body.get("client", "001"),
                language=body.get("language", "EN"),
                auth="cookie",
                username=(body.get("username") or "").strip() or None,
                password=(body.get("password") or "") or None,
                cookie_file=cookie_file, cookie_string=None))
        return JSONResponse({"result": result})

    @mcp.custom_route("/api/systems/{name}/refresh", methods=["POST"])
    async def api_refresh(request: Request) -> JSONResponse:
        """Re-login an existing cookie system and rewrite its cookie file.

        Uses stored username/password if present (headless), otherwise opens
        a visible browser for manual login.
        """
        try:
            sys = registry.get(request.path_params["name"])
        except KeyError:
            return JSONResponse({"result": "Error: unknown system"})
        if sys.auth != "cookie" or not sys.cookie_file:
            return JSONResponse({"result":
                "Error: refresh only applies to cookie_file systems"})
        # Saved credentials → silent headless refresh; only fall back to an
        # interactive browser login if that fails (or no creds are stored).
        if sys.username and sys.password:
            result = await anyio.to_thread.run_sync(
                refresh_cookies, sys.url, sys.username, sys.password,
                sys.cookie_file)
            if not result.startswith("OK"):
                result = await anyio.to_thread.run_sync(
                    interactive_login, sys.url, sys.cookie_file)
        else:
            result = await anyio.to_thread.run_sync(
                interactive_login, sys.url, sys.cookie_file)
        return JSONResponse({"result": result})

    return mcp
