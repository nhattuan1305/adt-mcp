"""HTTP client to fetch ABAP source from SAP ADT."""
import base64
import html
import re
import fnmatch
import difflib
import xml.etree.ElementTree as ET
import httpx
from urllib.parse import urlsplit, quote
from .registry import System


def check_write(system: System, package: str) -> str | None:
    """Safety gate: writes require allow_write + a whitelisted target package."""
    if not system.allow_write:
        return (f"Error: writes disabled for system {system.name!r} "
                f"(set allow_write=true in systems.json)")
    pats = system.write_packages or ["Z*", "$TMP"]
    pkg = (package or "").upper()
    if not pkg:
        return "Error: could not determine target package"
    if not any(fnmatch.fnmatch(pkg, p.upper()) for p in pats):
        return f"Error: package {package!r} not in write_packages {pats}"
    return None


def base_url(url: str) -> str:
    """Normalize a system URL to scheme://host, dropping any path/fragment
    (e.g. a Fiori launchpad URL like '.../ui#Shell-home')."""
    p = urlsplit(url if "//" in url else "https://" + url)
    return f"{p.scheme}://{p.netloc}"

OBJECT_PATHS = {
    "CLAS": "/sap/bc/adt/oo/classes/{name}/source/main",
    "INTF": "/sap/bc/adt/oo/interfaces/{name}/source/main",
    "PROG": "/sap/bc/adt/programs/programs/{name}/source/main",
    "INCL": "/sap/bc/adt/programs/includes/{name}/source/main",
    "FUGR": "/sap/bc/adt/functions/groups/{group}/fmodules/{name}/source/main",
    "DDLS": "/sap/bc/adt/ddic/ddl/sources/{name}/source/main",
    "BDEF": "/sap/bc/adt/bo/behaviordefinitions/{name}/source/main",
    "SRVD": "/sap/bc/adt/ddic/srvd/sources/{name}/source/main",
    "TABL": "/sap/bc/adt/ddic/tables/{name}/source/main",
    "VIEW": "/sap/bc/adt/ddic/views/{name}/source/main",
    "STRU": "/sap/bc/adt/ddic/structures/{name}/source/main",
    "DDLX": "/sap/bc/adt/ddic/ddlx/sources/{name}/source/main",
}

# Accept aliases for object types
OBJECT_TYPE_ALIASES = {"STRUCT": "STRU"}

CLASS_INCLUDES = {"definitions", "implementations", "macros", "testclasses"}


def object_root_path(object_type: str, name: str,
                     function_group: str | None = None) -> str:
    """ADT object root path (no /source/main, no host), for lock/unlock/activate."""
    ot = OBJECT_TYPE_ALIASES.get(object_type.upper(), object_type.upper())
    if ot == "FUGR":
        if not function_group:
            raise ValueError("FUGR requires function_group")
        return (f"/sap/bc/adt/functions/groups/{function_group.upper()}"
                f"/fmodules/{name.upper()}")
    if ot not in OBJECT_PATHS:
        raise ValueError(f"invalid object_type {object_type!r}")
    return OBJECT_PATHS[ot].format(
        name=name.upper(), group=(function_group or "").upper()
    ).rsplit("/source/main", 1)[0]


def parse_lock_result(data: bytes) -> tuple[str, str]:
    """Return (lock_handle, modification_support) from a LOCK response."""
    if not data:
        return "", ""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return "", ""
    handle, mod = "", ""
    for el in root.iter():
        ln = _localname(el.tag)
        if ln == "LOCK_HANDLE":
            handle = (el.text or "").strip()
        elif ln == "MODIFICATION_SUPPORT":
            mod = (el.text or "").strip()
    return handle, mod


def parse_lock_handle(data: bytes) -> str:
    """Extract the lock handle from a LOCK response."""
    return parse_lock_result(data)[0]


def parse_activation(data: bytes) -> str:
    """Return 'OK' or an error string from an activation response."""
    if not data:
        return "OK"
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return "OK"
    errors = []
    for el in root.iter():
        if _localname(el.tag) in ("msg", "message"):
            a = {_localname(k): v for k, v in el.attrib.items()}
            sev = (a.get("severity") or a.get("type") or "").upper()
            text = a.get("shortText") or (el.text or "")
            if sev and sev[0] in ("E", "A", "X"):
                errors.append(text.strip() or sev)
    return "Error: activation failed: " + "; ".join(errors) if errors else "OK"


def parse_check_run(data: bytes) -> list[dict]:
    """Parse a checkruns response into message dicts.

    Each message: {type (E/W/I/...), text, uri, line}. type is the severity
    letter ADT returns (E=error, W=warning, I=info, S=success).
    """
    if not data:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if _localname(el.tag) != "checkMessage":
            continue
        a = {_localname(k): v for k, v in el.attrib.items()}
        uri = a.get("uri", "")
        line = ""
        m = re.search(r"start=(\d+)", uri)
        if m:
            line = m.group(1)
        out.append({
            "type": (a.get("type") or "").upper(),
            "text": a.get("shortText") or (el.text or "").strip(),
            "uri": uri,
            "line": line,
        })
    return out


def parse_release_state(data: bytes) -> dict:
    """Parse an apireleases response into a release-state dict.

    Returns {object: {name,type}, contracts: [{contract, state,
    stateDescription, cloud, keyUser, successors:[name]}],
    anyContractReleased: bool}.
    """
    text = (data or b"").decode("utf-8", "replace").strip()
    # The endpoint sometimes returns the XML JSON-quoted / HTML-escaped.
    if text[:1] == '"' and text[-1:] == '"':
        text = text[1:-1].encode().decode("unicode_escape")
    if "&lt;" in text:
        text = html.unescape(text)
    out: dict = {"object": {}, "contracts": [], "anyContractReleased": False}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    for el in root.iter():
        ln = _localname(el.tag)
        a = {_localname(k): v for k, v in el.attrib.items()}
        if ln == "releasableObject":
            out["object"] = {"name": a.get("name", ""),
                             "type": a.get("type", ""),
                             "uri": a.get("uri", "")}
        elif ln.endswith("Release") and ln != "apiRelease":
            c = {"contract": a.get("contract", "") or ln.replace("Release", ""),
                 "state": "", "stateDescription": "",
                 "cloud": a.get("useInSAPCloudPlatform", "") == "true",
                 "keyUser": a.get("useInKeyUserApps", "") == "true",
                 "successors": []}
            for ch in el.iter():
                cln = _localname(ch.tag)
                ca = {_localname(k): v for k, v in ch.attrib.items()}
                if cln == "status":
                    c["state"] = ca.get("state", "")
                    c["stateDescription"] = ca.get("stateDescription", "")
                elif cln == "successor" and ca.get("name"):
                    c["successors"].append(ca["name"])
            out["contracts"].append(c)
        elif ln == "apiCatalogData":
            out["anyContractReleased"] = \
                a.get("isAnyContractReleased", "") == "true"
    return out


def parse_netscape_cookies(text: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


def is_login_page(resp: httpx.Response) -> bool:
    """A 200 response that is actually a SAML/SSO login page, not ADT content.

    SAP cloud (S/4HANA, BTP) answers an expired session with HTTP 200 carrying
    an HTML SAML auto-submit form instead of the requested ADT payload. ADT
    source/discovery responses are text/plain or */xml, never text/html.
    """
    ctype = resp.headers.get("content-type", "").lower()
    if "text/html" in ctype:
        return True
    body = resp.text
    return "SAMLRequest" in body or "saml2/idp" in body.lower()


def _localname(tag: str) -> str:
    """Strip XML namespace from a tag, e.g. '{ns}name' -> 'name'."""
    return tag.rsplit("}", 1)[-1]


def parse_nodestructure(data: bytes) -> list[dict]:
    """Parse a repository/nodestructure response into object dicts."""
    if not data:
        return []
    root = ET.fromstring(data)
    out = []
    for node in root.iter():
        if _localname(node.tag) != "SEU_ADT_REPOSITORY_OBJ_NODE":
            continue
        fields = {_localname(c.tag): (c.text or "").strip() for c in node}
        name = fields.get("OBJECT_NAME", "")
        if not name:
            continue
        out.append({
            "type": fields.get("OBJECT_TYPE", ""),
            "name": name,
            "uri": fields.get("OBJECT_URI", ""),
            "description": fields.get("DESCRIPTION", ""),
        })
    return out


def parse_search(data: bytes) -> list[dict]:
    """Parse an informationsystem/search response into object dicts."""
    if not data:
        return []
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        attrs = {_localname(k): v for k, v in el.attrib.items()}
        name = attrs.get("name")
        if not name or "type" not in attrs:
            continue
        out.append({
            "name": name,
            "type": attrs.get("type", ""),
            "uri": attrs.get("uri", ""),
            "package": attrs.get("packageName", ""),
            "description": attrs.get("description", ""),
        })
    return out


def extract_method(source: str, method: str) -> str | None:
    """Return the METHOD <method> … ENDMETHOD block from class source."""
    lines = source.splitlines()
    start = re.compile(rf"^\s*METHOD\s+{re.escape(method)}\s*\.", re.IGNORECASE)
    end = re.compile(r"^\s*ENDMETHOD\s*\.", re.IGNORECASE)
    for i, line in enumerate(lines):
        if start.match(line):
            for j in range(i, len(lines)):
                if end.match(lines[j]):
                    return "\n".join(lines[i:j + 1])
            return "\n".join(lines[i:])
    return None


def parse_revision_feed(data: bytes) -> list[dict]:
    """Parse an ADT revisions atom feed into version dicts."""
    if not data:
        return []
    root = ET.fromstring(data)
    out = []
    for entry in root.iter():
        if _localname(entry.tag) != "entry":
            continue
        rev = {"version": "", "title": "", "date": "", "author": "",
               "transport": "", "uri": ""}
        for ch in entry:
            ln = _localname(ch.tag)
            if ln == "id":
                rev["version"] = (ch.text or "").strip()
            elif ln == "title":
                rev["title"] = (ch.text or "").strip()
            elif ln == "updated":
                rev["date"] = (ch.text or "").strip()
            elif ln == "author":
                for a in ch:
                    if _localname(a.tag) == "name":
                        rev["author"] = (a.text or "").strip()
            elif ln == "content":
                attrs = {_localname(k): v for k, v in ch.attrib.items()}
                rev["uri"] = attrs.get("src", "")
            elif ln == "link":
                attrs = {_localname(k): v for k, v in ch.attrib.items()}
                if "transportrequests" in attrs.get("type", ""):
                    rev["transport"] = attrs.get("name", "")
        out.append(rev)
    return out


REVISION_PATHS = {
    "PROG": "/sap/bc/adt/programs/programs/{name}/source/main/versions",
    "INTF": "/sap/bc/adt/oo/interfaces/{name}/includes/main/versions",
    "INCL": "/sap/bc/adt/programs/includes/{name}/source/main/versions",
    "DDLS": "/sap/bc/adt/ddic/ddl/sources/{name}/source/main/versions",
    "BDEF": "/sap/bc/adt/bo/behaviordefinitions/{name}/source/main/versions",
    "SRVD": "/sap/bc/adt/ddic/srvd/sources/{name}/source/main/versions",
}


def revision_url(object_type: str, name: str,
                 function_group: str | None = None,
                 include: str | None = None) -> str:
    ot = OBJECT_TYPE_ALIASES.get(object_type.upper(), object_type.upper())
    n = name.upper()
    if ot == "CLAS":
        return (f"/sap/bc/adt/oo/classes/{n}/includes/"
                f"{(include or 'main').lower()}/versions")
    if ot in ("FUGR", "FUNC"):
        if not function_group:
            raise ValueError("function_group required for function revisions")
        return (f"/sap/bc/adt/functions/groups/{function_group.upper()}"
                f"/fmodules/{n}/source/main/versions")
    if ot in REVISION_PATHS:
        return REVISION_PATHS[ot].format(name=n)
    raise ValueError(
        f"unsupported object_type for revisions {object_type!r}; valid: "
        f"PROG, CLAS, INTF, FUNC, INCL, DDLS, BDEF, SRVD")


def parse_cds_dependencies(source: str) -> list[dict]:
    """Extract upstream dependencies from CDS/DDL source text.

    Returns dicts {relation, name} for FROM / JOIN / ASSOCIATION / COMPOSITION
    targets. Pure text parse — works wherever the source can be read.
    """
    out, seen = [], set()
    patterns = [
        ("FROM", r"\bfrom\s+([A-Za-z_/][\w/]*)"),
        ("PROJECTION", r"\bprojection\s+on\s+([A-Za-z_/][\w/]*)"),
        ("JOIN", r"\bjoin\s+([A-Za-z_/][\w/]*)"),
        ("ASSOCIATION", r"\bassociation(?:\s*\[[^\]]*\])?\s+to\s+(?:parent\s+)?([A-Za-z_/][\w/]*)"),
        ("COMPOSITION", r"\bcomposition(?:\s*\[[^\]]*\])?\s+of\s+([A-Za-z_/][\w/]*)"),
    ]
    for relation, pat in patterns:
        for m in re.finditer(pat, source, re.IGNORECASE):
            name = m.group(1)
            if name.lower() in ("select", "as"):
                continue
            key = (relation, name.upper())
            if key not in seen:
                seen.add(key)
                out.append({"relation": relation, "name": name})
    return out


def compress_source(object_type: str, source: str) -> str:
    """Strip a dependency's source down to the parts that matter for context.

    DDLS/CDS: drop @annotations and // comments (keep define/select/fields).
    CLAS: keep the DEFINITION part (signatures), drop method implementations.
    Other types: returned as-is (already concise).
    """
    ot = object_type.upper()
    if ot == "DDLS":
        keep = []
        for line in source.splitlines():
            s = line.strip()
            if not s or s.startswith("@") or s.startswith("//"):
                continue
            keep.append(line.rstrip())
        return "\n".join(keep)
    if ot == "CLAS":
        m = re.search(r"^\s*class\s+\S+\s+implementation", source,
                      re.IGNORECASE | re.MULTILINE)
        if m:
            return source[:m.start()].rstrip()
        return source
    return source


def parse_usage_references(data: bytes) -> list[dict]:
    """Parse a usageReferences response into where-used dicts."""
    if not data:
        return []
    root = ET.fromstring(data)
    out = []
    for ref in root.iter():
        if _localname(ref.tag) != "referencedObject":
            continue
        rattrs = {_localname(k): v for k, v in ref.attrib.items()}
        info = {"name": "", "type": "", "uri": rattrs.get("uri", ""),
                "package": "", "description": "",
                "usage": rattrs.get("usageInformation", "")}
        for child in ref:
            if _localname(child.tag) == "adtObject":
                a = {_localname(k): v for k, v in child.attrib.items()}
                info["name"] = a.get("name", "")
                info["type"] = a.get("type", "")
                info["description"] = a.get("description", "")
                for gc in child:
                    if _localname(gc.tag) == "packageRef":
                        pa = {_localname(k): v for k, v in gc.attrib.items()}
                        info["package"] = pa.get("name", "")
        if info["name"] or info["uri"]:
            out.append(info)
    return out


def list_method_decls(source: str) -> list[str]:
    """Return declared method names (METHODS / CLASS-METHODS) in order."""
    pat = re.compile(r"^\s*(?:CLASS-METHODS|METHODS)\s+([A-Za-z_]\w*)",
                     re.IGNORECASE)
    seen, out = set(), []
    for line in source.splitlines():
        m = pat.match(line)
        if m:
            n = m.group(1).upper()
            if n not in seen:
                seen.add(n)
                out.append(n)
    return out


# Create templates: type -> (creation_path, root_elem, ns_decl, adt_type,
#                            content_type, source_capable)
CREATE_TYPES = {
    "PROG": ("/sap/bc/adt/programs/programs", "program:abapProgram",
             'xmlns:program="http://www.sap.com/adt/programs/programs"',
             "PROG/P", "application/*", True),
    "CLAS": ("/sap/bc/adt/oo/classes", "class:abapClass",
             'xmlns:class="http://www.sap.com/adt/oo/classes"',
             "CLAS/OC", "application/*", True),
    "INTF": ("/sap/bc/adt/oo/interfaces", "intf:abapInterface",
             'xmlns:intf="http://www.sap.com/adt/oo/interfaces"',
             "INTF/OI", "application/*", True),
    "DDLS": ("/sap/bc/adt/ddic/ddl/sources", "ddl:ddlSource",
             'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
             "DDLS/DF", "application/*", True),
    "DDLX": ("/sap/bc/adt/ddic/ddlx/sources", "ddlx:ddlxSource",
             'xmlns:ddlx="http://www.sap.com/adt/ddic/ddlxsources"',
             "DDLX/EX", "application/*", True),
    "BDEF": ("/sap/bc/adt/bo/behaviordefinitions", "blue:blueSource",
             'xmlns:blue="http://www.sap.com/wbobj/blue"',
             "BDEF/BDO", "application/vnd.sap.adt.blues.v1+xml", True),
    "SRVD": ("/sap/bc/adt/ddic/srvd/sources", "srvd:srvdSource",
             'xmlns:srvd="http://www.sap.com/adt/ddic/srvdsources"',
             "SRVD/SRV", "application/*", True),
    "SRVB": ("/sap/bc/adt/businessservices/bindings", "srvb:serviceBinding",
             'xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings"',
             "SRVB/SVB", "application/*", False),
    "TABL": ("/sap/bc/adt/ddic/tables", "blue:blueSource",
             'xmlns:blue="http://www.sap.com/wbobj/blue"',
             "TABL/DT", "application/*", True),
}


def build_creation_body(object_type: str, name: str, package: str,
                        description: str, responsible: str,
                        service_definition: str | None = None,
                        binding_version: str = "V2") -> str:
    ot = object_type.upper()
    path, root, ns, adt_type, _ct, _sc = CREATE_TYPES[ot]
    name = name.upper()
    package = package.upper()
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:description="{description}" adtcore:name="{name}" '
            f'adtcore:type="{adt_type}" adtcore:responsible="{responsible}"')
    if ot == "SRVD":
        head += ' srvd:srvdSourceType="S"'
    if ot == "SRVB":
        return (head + '>\n'
                f'  <adtcore:packageRef adtcore:name="{package}"/>\n'
                f'  <srvb:services srvb:name="{name}">\n'
                f'    <srvb:content srvb:version="0001">\n'
                f'      <srvb:serviceDefinition adtcore:name='
                f'"{(service_definition or "").upper()}"/>\n'
                f'    </srvb:content>\n  </srvb:services>\n'
                f'  <srvb:binding srvb:category="0" srvb:type="ODATA" '
                f'srvb:version="{binding_version}">\n'
                f'    <srvb:implementation adtcore:name=""/>\n'
                f'  </srvb:binding>\n</{root}>')
    return (head + '>\n'
            f'  <adtcore:packageRef adtcore:name="{package}"/>\n</{root}>')


class ADTClient:
    def __init__(self, client: httpx.Client):
        self._client = client

    def source_url(self, system: System, object_type: str, name: str,
                   function_group: str | None) -> str:
        ot = object_type.upper()
        ot = OBJECT_TYPE_ALIASES.get(ot, ot)
        if ot not in OBJECT_PATHS:
            raise ValueError(
                f"invalid object_type {object_type!r}; "
                f"valid: {', '.join(OBJECT_PATHS)}")
        if ot == "FUGR" and not function_group:
            raise ValueError("FUGR requires function_group")
        path = OBJECT_PATHS[ot].format(
            name=name.upper(),
            group=(function_group or "").upper())
        return (f"{base_url(system.url)}{path}"
                f"?sap-client={system.client}"
                f"&sap-language={system.language}")

    def _cookies_dict(self, system: System) -> dict | None:
        """Session cookies as a dict (for stateful write sequences)."""
        if system.auth != "cookie":
            return None
        if system.cookie_string:
            out = {}
            for part in system.cookie_string.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k.strip()] = v.strip()
            return out
        if system.cookie_file:
            with open(system.cookie_file, encoding="utf-8") as f:
                return parse_netscape_cookies(f.read())
        return None

    def _auth_kwargs(self, system: System) -> dict:
        if system.auth == "cookie":
            if system.cookie_string:
                return {"headers": {"Cookie": system.cookie_string}}
            if system.cookie_file:
                with open(system.cookie_file, encoding="utf-8") as f:
                    cookies = parse_netscape_cookies(f.read())
                return {"headers": {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}}
            return {}
        return {"auth": httpx.BasicAuth(system.username or "",
                                        system.password or "")}

    def _get(self, system: System, url: str, accept: str):
        """Low-level GET with auth + accept. Returns httpx.Response or raises."""
        kwargs = self._auth_kwargs(system)
        headers = kwargs.pop("headers", {})
        headers["Accept"] = accept
        return self._client.get(url, headers=headers, **kwargs)

    def _csrf_token(self, system: System) -> str:
        """Fetch a CSRF token for the current session (needed for POSTs)."""
        url = f"{base_url(system.url)}/sap/bc/adt/discovery"
        kwargs = self._auth_kwargs(system)
        headers = kwargs.pop("headers", {})
        headers["X-CSRF-Token"] = "fetch"
        headers["Accept"] = "application/atomsvc+xml"
        try:
            resp = self._client.get(url, headers=headers, **kwargs)
        except httpx.HTTPError:
            return ""
        return resp.headers.get("x-csrf-token", "")

    def _post(self, system: System, url: str, accept: str,
              body: bytes | None = None, content_type: str | None = None):
        """Low-level POST with auth + accept + CSRF token. Returns response or raises."""
        kwargs = self._auth_kwargs(system)
        headers = kwargs.pop("headers", {})
        headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type
        token = self._csrf_token(system)
        if token:
            headers["X-CSRF-Token"] = token
        if body is not None:
            kwargs["content"] = body
        return self._client.post(url, headers=headers, **kwargs)

    def _fetch_source(self, system: System, url: str, label: str) -> str:
        """GET a source URL; return text or a human-readable error string."""
        try:
            resp = self._get(system, url, "text/plain")
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code == 200:
            if is_login_page(resp):
                return (f"Error: session expired for system {system.name!r} "
                        f"(got SAML login page) — refresh cookies and retry")
            return resp.text
        if resp.status_code in (401, 403):
            return (f"Error: auth failed (HTTP {resp.status_code}) — "
                    f"cookie expired or wrong credentials for "
                    f"system {system.name!r}")
        if resp.status_code == 404:
            return f"Error: object not found ({label})"
        return f"Error: HTTP {resp.status_code}: {resp.text[:300]}"

    def get_source(self, system: System, object_type: str, name: str,
                   function_group: str | None = None) -> str:
        try:
            url = self.source_url(system, object_type, name, function_group)
        except ValueError as e:
            return f"Error: {e}"
        return self._fetch_source(system, url, f"{object_type} {name}")

    def test_connection(self, system: System) -> str:
        url = f"{base_url(system.url)}/sap/bc/adt/discovery"
        kwargs = self._auth_kwargs(system)
        headers = kwargs.pop("headers", {})
        try:
            resp = self._client.get(url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code == 200:
            if is_login_page(resp):
                return (f"Error: session expired for system {system.name!r} "
                        f"(got SAML login page) — refresh cookies and retry")
            return "OK"
        if resp.status_code in (401, 403):
            return f"Error: auth failed (HTTP {resp.status_code})"
        return f"Error: HTTP {resp.status_code}"

    # --- Navigation / discovery (v2 Phase 1) ---

    def get_source_by_uri(self, system: System, uri: str) -> str:
        """Fetch source for any object given its ADT URI (from list/search)."""
        if not uri:
            return "Error: empty uri"
        path = uri if "/source/main" in uri else uri.rstrip("/") + "/source/main"
        url = (f"{base_url(system.url)}{path}"
               f"?sap-client={system.client}&sap-language={system.language}")
        return self._fetch_source(system, url, uri)

    def get_class_include(self, system: System, class_name: str,
                          include: str) -> str:
        inc = include.lower()
        if inc not in CLASS_INCLUDES:
            return (f"Error: invalid include {include!r}; "
                    f"valid: {', '.join(sorted(CLASS_INCLUDES))}")
        url = (f"{base_url(system.url)}/sap/bc/adt/oo/classes/"
               f"{class_name.upper()}/includes/{inc}"
               f"?sap-client={system.client}&sap-language={system.language}")
        return self._fetch_source(system, url, f"{class_name} {inc}")

    def get_class_method_source(self, system: System, class_name: str,
                                method: str) -> str:
        source = self.get_source(system, "CLAS", class_name)
        if source.startswith("Error:"):
            return source
        block = extract_method(source, method.upper())
        if block is None:
            return f"Error: method {method} not found in class {class_name}"
        return block

    def object_structure(self, system: System, class_name: str) -> list[str] | str:
        source = self.get_source(system, "CLAS", class_name)
        if source.startswith("Error:"):
            return source
        return list_method_decls(source)

    def list_package(self, system: System, package: str,
                     recursive: bool = False) -> list[dict] | str:
        result: list[dict] = []
        visited: set[str] = set()

        def fetch(pkg: str) -> str | None:
            url = (f"{base_url(system.url)}/sap/bc/adt/repository/nodestructure"
                   f"?parent_type=DEVC/K&parent_name={pkg.upper()}"
                   f"&withShortDescriptions=true")
            try:
                resp = self._post(system, url, "*/*")
            except httpx.HTTPError as e:
                return f"Error: request failed: {e}"
            if resp.status_code != 200:
                return f"Error: HTTP {resp.status_code} listing package {pkg}"
            if is_login_page(resp):
                return (f"Error: session expired for system {system.name!r} "
                        f"— refresh cookies and retry")
            for obj in parse_nodestructure(resp.content):
                obj["package"] = pkg.upper()
                result.append(obj)
                if recursive and obj["type"] == "DEVC/K" \
                        and obj["name"] not in visited:
                    visited.add(obj["name"])
                    err = fetch(obj["name"])
                    if err:
                        return err
            return None

        err = fetch(package)
        if err:
            return err
        return result

    def search_objects(self, system: System, query: str,
                       max_results: int = 20) -> list[dict] | str:
        url = (f"{base_url(system.url)}/sap/bc/adt/repository/"
               f"informationsystem/search?operation=quickSearch"
               f"&query={query}&maxResults={max_results}")
        try:
            resp = self._get(system, url, "application/xml")
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code}"
        if is_login_page(resp):
            return (f"Error: session expired for system {system.name!r} "
                    f"— refresh cookies and retry")
        return parse_search(resp.content)

    def get_package_source(self, system: System, package: str,
                           max_objects: int = 50) -> str:
        objs = self.list_package(system, package)
        if isinstance(objs, str):
            return objs
        sources = [o for o in objs if o["type"] != "DEVC/K" and o["uri"]]
        if not sources:
            return f"No source objects in package {package}"
        chunks, used, truncated = [], 0, False
        for o in sources:
            if used >= max_objects:
                truncated = True
                break
            src = self.get_source_by_uri(system, o["uri"])
            if src.startswith("Error:"):
                continue
            chunks.append(f"* ==== {o['type']} {o['name']} ====\n{src}")
            used += 1
        if not chunks:
            return f"No readable source in package {package}"
        out = "\n\n".join(chunks)
        if truncated:
            out += (f"\n\n* ==== truncated at {max_objects} objects "
                    f"({len(sources)} total) ====")
        return out

    def grep_package(self, system: System, package: str, pattern: str,
                     ignore_case: bool = False, max_objects: int = 100) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return f"Error: invalid pattern: {e}"
        objs = self.list_package(system, package)
        if isinstance(objs, str):
            return objs
        sources = [o for o in objs if o["type"] != "DEVC/K" and o["uri"]]
        matches, scanned = [], 0
        for o in sources:
            if scanned >= max_objects:
                break
            scanned += 1
            src = self.get_source_by_uri(system, o["uri"])
            if src.startswith("Error:"):
                continue
            for n, line in enumerate(src.splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{o['name']}:{n}: {line.strip()}")
        if not matches:
            return f"No matches for {pattern!r} in package {package}"
        return "\n".join(matches)

    # --- History / Diff (v2 Phase 2) ---

    def get_revisions(self, system: System, object_type: str, name: str,
                      function_group: str | None = None,
                      include: str | None = None) -> list[dict] | str:
        try:
            path = revision_url(object_type, name, function_group, include)
        except ValueError as e:
            return f"Error: {e}"
        url = (f"{base_url(system.url)}{path}"
               f"?sap-client={system.client}&sap-language={system.language}")
        try:
            resp = self._get(system, url, "application/atom+xml;type=feed")
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code == 200:
            if is_login_page(resp):
                return (f"Error: session expired for system {system.name!r} "
                        f"— refresh cookies and retry")
            return parse_revision_feed(resp.content)
        if resp.status_code == 404:
            return f"Error: object not found ({object_type} {name})"
        return f"Error: HTTP {resp.status_code}"

    def get_revision_source(self, system: System, version_uri: str) -> str:
        if not version_uri:
            return "Error: empty version_uri"
        url = f"{base_url(system.url)}{version_uri}"
        return self._fetch_source(system, url, version_uri)

    def compare_source(self, system: System, object_type: str, name: str,
                       version_uri: str, against: str = "current",
                       function_group: str | None = None) -> str:
        src1 = self.get_revision_source(system, version_uri)
        if src1.startswith("Error:"):
            return src1
        if against == "current":
            src2 = self.get_source(system, object_type, name, function_group)
            label2 = f"{name}@current"
        else:
            src2 = self.get_revision_source(system, against)
            label2 = f"{name}@{against.rsplit('/', 2)[0].rsplit('/', 1)[-1]}"
        if src2.startswith("Error:"):
            return src2
        if src1 == src2:
            return "Sources are identical"
        diff = difflib.unified_diff(
            src1.splitlines(), src2.splitlines(),
            fromfile=f"{name}@revision", tofile=label2, lineterm="")
        return "\n".join(diff)

    # --- Code intelligence (v2 Phase 3) ---

    def find_references(self, system: System, object_uri: str,
                        line: int = 0, column: int = 0) -> list[dict] | str:
        """Where-used list for an object (or a symbol at line/column)."""
        if not object_uri:
            return "Error: object_uri is required"
        uri = object_uri
        if line > 0 and column > 0:
            uri = f"{object_uri}#start={line},{column}"
        url = (f"{base_url(system.url)}/sap/bc/adt/repository/"
               f"informationsystem/usageReferences?uri={quote(uri, safe='')}")
        body = (b'<?xml version="1.0" encoding="ASCII"?>'
                b'<usagereferences:usageReferenceRequest '
                b'xmlns:usagereferences="http://www.sap.com/adt/ris/usageReferences">'
                b'<usagereferences:affectedObjects/>'
                b'</usagereferences:usageReferenceRequest>')
        try:
            resp = self._post(system, url, "application/*", body, "application/*")
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code == 200:
            if is_login_page(resp):
                return (f"Error: session expired for system {system.name!r} "
                        f"— refresh cookies and retry")
            return parse_usage_references(resp.content)
        if resp.status_code == 404:
            return f"Error: object not found ({object_uri})"
        return f"Error: HTTP {resp.status_code}: {resp.text[:200]}"

    # --- CDS analysis (v2 Phase 4) ---

    def cds_dependencies(self, system: System, ddls_name: str) -> list[dict] | str:
        """Upstream dependencies of a CDS view, parsed from its DDL source."""
        source = self.get_source(system, "DDLS", ddls_name)
        if source.startswith("Error:"):
            return source
        return parse_cds_dependencies(source)

    # --- Syntax check (ABAP check run) ---

    def syntax_check(self, system: System, object_type: str, name: str,
                     function_group: str | None = None,
                     version: str = "active",
                     source: str | None = None) -> str:
        """Run the ABAP syntax/check-run for an object; return findings text.

        The source to check is embedded as a base64 artifact (the check-run
        reporter checks the supplied content, not the stored version — without
        an artifact the server returns no messages, a false OK). If `source`
        is omitted, the current active source is fetched and checked.

        version: kept for the checkObject element ('active'/'inactive').
        Returns 'OK: no syntax errors' when clean.
        """
        try:
            root_path = object_root_path(object_type, name, function_group)
        except ValueError as e:
            return f"Error: {e}"
        if source is None:
            source = self.get_source(system, object_type, name, function_group)
            if source.startswith("Error:"):
                return source
        artifact_uri = f"{root_path}/source/main"
        encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<chkrun:checkObjectList '
            f'xmlns:chkrun="http://www.sap.com/adt/checkrun" '
            f'xmlns:adtcore="http://www.sap.com/adt/core">'
            f'<chkrun:checkObject adtcore:uri="{root_path}" '
            f'chkrun:version="{version}">'
            f'<chkrun:artifacts>'
            f'<chkrun:artifact '
            f'chkrun:contentType="text/plain; charset=utf-8" '
            f'chkrun:uri="{artifact_uri}">'
            f'<chkrun:content>{encoded}</chkrun:content>'
            f'</chkrun:artifact>'
            f'</chkrun:artifacts>'
            f'</chkrun:checkObject>'
            f'</chkrun:checkObjectList>').encode("utf-8")
        url = (f"{base_url(system.url)}/sap/bc/adt/checkruns"
               f"?reporters=abapCheckRun")
        try:
            resp = self._post(
                system, url, "application/*", body, "application/*")
        except httpx.HTTPError as e:
            return f"Error: check request failed: {e}"
        if resp.status_code != 200:
            return (f"Error: syntax check failed (HTTP {resp.status_code}): "
                    f"{resp.text[:300]}")
        if is_login_page(resp):
            return (f"Error: session expired for system {system.name!r} "
                    f"— refresh cookies and retry")
        msgs = parse_check_run(resp.content)
        errors = [m for m in msgs if m["type"][:1] in ("E", "A", "X")]
        warnings = [m for m in msgs if m["type"][:1] == "W"]
        if not errors and not warnings:
            return f"OK: no syntax errors ({object_type.upper()} {name.upper()})"

        def fmt(m: dict) -> str:
            loc = f":{m['line']}" if m["line"] else ""
            return f"{m['type']}{loc}: {m['text']}"

        lines = [f"{len(errors)} error(s), {len(warnings)} warning(s) "
                 f"in {object_type.upper()} {name.upper()}:"]
        lines += [fmt(m) for m in errors + warnings]
        return "\n".join(lines)

    # --- Pretty printer (ABAP source formatter) ---

    def pretty_print(self, system: System, source: str) -> str:
        """Format ABAP source via the ADT pretty printer (user's settings)."""
        if not source:
            return "Error: empty source"
        url = (f"{base_url(system.url)}/sap/bc/adt/abapsource/prettyprinter"
               f"?sap-client={system.client}")
        try:
            resp = self._post(system, url, "text/plain",
                              source.encode("utf-8"), "text/plain")
        except httpx.HTTPError as e:
            return f"Error: pretty print request failed: {e}"
        if resp.status_code != 200:
            return (f"Error: pretty print failed (HTTP {resp.status_code}): "
                    f"{resp.text[:300]}")
        if is_login_page(resp):
            return (f"Error: session expired for system {system.name!r} "
                    f"— refresh cookies and retry")
        # Empty body => server returned nothing to change; keep the original.
        return resp.text if resp.text else source

    # --- API release state (ABAP Cloud / Clean Core) ---

    def api_release_state(self, system: System, object_type: str, name: str,
                          function_group: str | None = None) -> str:
        """Report the API release state of an object (released for ABAP Cloud?)."""
        try:
            root_path = object_root_path(object_type, name, function_group)
        except ValueError as e:
            return f"Error: {e}"
        endpoint = (f"{base_url(system.url)}/sap/bc/adt/apireleases/"
                    f"{quote(root_path, safe='')}"
                    f"?sap-client={system.client}")
        try:
            resp = self._get(
                system, endpoint,
                "application/vnd.sap.adt.apirelease.v10+xml")
        except httpx.HTTPError as e:
            return f"Error: request failed: {e}"
        if resp.status_code == 404:
            return (f"Error: no release info ({object_type.upper()} "
                    f"{name.upper()}) — object unknown or not releasable")
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code}: {resp.text[:200]}"
        if is_login_page(resp):
            return (f"Error: session expired for system {system.name!r} "
                    f"— refresh cookies and retry")
        st = parse_release_state(resp.content)
        obj = st["object"] or {"name": name.upper(), "type": object_type.upper()}
        # Drop empty contract-slot placeholders (no state/flags/successors).
        contracts = [c for c in st["contracts"]
                     if c["state"] or c["cloud"] or c["keyUser"]
                     or c["successors"]]
        cloud_ok = any(c["cloud"] and c["state"] == "RELEASED"
                       for c in contracts)
        head = (f"{obj.get('name', name.upper())} "
                f"({obj.get('type', object_type.upper())}) - "
                + ("RELEASED for ABAP Cloud" if cloud_ok
                   else "NOT released for ABAP Cloud"))
        lines = [head]
        if not contracts:
            lines.append("  (no release contracts)")
        for c in contracts:
            succ = (f"  successors: {', '.join(c['successors'])}"
                    if c["successors"] else "")
            lines.append(
                f"  {c['contract']}: {c['state'] or '?'}"
                f" ({c['stateDescription'] or '-'})"
                f"  cloud={'yes' if c['cloud'] else 'no'}"
                f" keyUser={'yes' if c['keyUser'] else 'no'}{succ}")
        return "\n".join(lines)

    # --- Context compression (v2 Phase 6) ---

    def get_context(self, system: System, object_type: str, name: str,
                    depth: int = 1, max_objects: int = 20) -> str:
        """Bundle an object's full source + compressed CDS dependencies.

        v1 resolves dependencies for CDS (DDLS) objects via their source
        (FROM/JOIN/ASSOCIATION/COMPOSITION), recursing up to `depth`. Custom
        (Z*/Y*/namespaced) deps are fetched and compressed; standard SAP
        objects are listed but not expanded (token economy).
        """
        main = self.get_source(system, object_type, name)
        if main.startswith("Error:"):
            return main
        ot = object_type.upper()
        blocks = [f"* ==== {ot} {name.upper()} (full source) ====", main]
        if ot != "DDLS":
            return "\n".join(blocks)

        visited = {name.upper()}
        frontier = [(name, 1)]
        count = 0
        while frontier and count < max_objects:
            cur, lvl = frontier.pop(0)
            deps = self.cds_dependencies(system, cur)
            if isinstance(deps, str):
                continue
            for d in deps:
                dn, up = d["name"], d["name"].upper()
                if up in visited:
                    continue
                visited.add(up)
                count += 1
                if count > max_objects:
                    break
                is_custom = up[:1] in ("Z", "Y") or up.startswith("/")
                if not is_custom:
                    blocks.append(f"* ---- {d['relation']} {dn} "
                                  f"(standard, not expanded) ----")
                    continue
                src = self.get_source(system, "DDLS", dn)
                otype = "DDLS"
                if src.startswith("Error: object not found"):
                    src = self.get_source(system, "TABL", dn)
                    otype = "TABL"
                if src.startswith("Error:"):
                    blocks.append(f"* ---- {d['relation']} {dn} (unresolved) ----")
                    continue
                blocks.append(f"* ---- {d['relation']} {dn} "
                              f"[{otype}, compressed] ----")
                blocks.append(compress_source(otype, src))
                if otype == "DDLS" and lvl < depth:
                    frontier.append((dn, lvl + 1))
        return "\n".join(blocks)

    # --- Write: stateful primitives (v_write Phase A) ---

    def object_root_url(self, system: System, object_type: str, name: str,
                        function_group: str | None = None) -> str:
        return f"{base_url(system.url)}{object_root_path(object_type, name, function_group)}"

    def _write_kwargs(self, system: System) -> dict:
        """Auth kwargs for the stateful write sequence (cookies as dict)."""
        if system.auth == "cookie":
            cookies = self._cookies_dict(system) or {}
            return {"cookies": cookies}
        return {"auth": httpx.BasicAuth(system.username or "",
                                        system.password or "")}

    def _lock(self, system: System, root_url: str, token: str,
              wk: dict) -> tuple[str, str | None]:
        url = f"{root_url}?_action=LOCK&accessMode=MODIFY"
        headers = {"X-sap-adt-sessiontype": "stateful", "X-CSRF-Token": token,
                   "Accept": "application/vnd.sap.as+xml;charset=UTF-8;"
                             "dataname=com.sap.adt.lock.result"}
        try:
            resp = self._client.post(url, headers=headers, **wk)
        except httpx.HTTPError as e:
            return "", f"Error: lock request failed: {e}"
        if resp.status_code != 200:
            return "", f"Error: lock failed (HTTP {resp.status_code}): {resp.text[:200]}"
        handle, _mod = parse_lock_result(resp.content)
        # Note: MODIFICATION_SUPPORT="NoModification" is informational on cloud
        # (local / no version mgmt) and does NOT block writes — a PUT with the
        # handle still succeeds. Only a missing handle is a real failure.
        if not handle:
            return "", f"Error: no lock handle returned: {resp.text[:200]}"
        return handle, None

    def _put_source(self, system: System, source_url: str, source: str,
                    handle: str, transport: str | None, token: str,
                    wk: dict) -> str | None:
        url = f"{source_url}&lockHandle={quote(handle, safe='')}"
        if transport:
            url += f"&corrNr={quote(transport, safe='')}"
        headers = {"X-sap-adt-sessiontype": "stateful", "X-CSRF-Token": token,
                   "Content-Type": "text/plain; charset=utf-8"}
        try:
            resp = self._client.put(url, headers=headers,
                                    content=source.encode("utf-8"), **wk)
        except httpx.HTTPError as e:
            return f"Error: update request failed: {e}"
        if resp.status_code in (200, 201, 202):
            return None
        return f"Error: update failed (HTTP {resp.status_code}): {resp.text[:300]}"

    def _unlock(self, system: System, root_url: str, handle: str,
                token: str, wk: dict) -> None:
        url = f"{root_url}?_action=UNLOCK&lockHandle={quote(handle, safe='')}"
        headers = {"X-sap-adt-sessiontype": "stateful", "X-CSRF-Token": token}
        try:
            self._client.post(url, headers=headers, **wk)
        except httpx.HTTPError:
            pass

    def activate(self, system: System, object_type: str, name: str,
                 function_group: str | None = None) -> str:
        try:
            root_path = object_root_path(object_type, name, function_group)
        except ValueError as e:
            return f"Error: {e}"
        body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<adtcore:objectReferences '
                f'xmlns:adtcore="http://www.sap.com/adt/core">'
                f'<adtcore:objectReference adtcore:uri="{root_path}" '
                f'adtcore:name="{name.upper()}"/>'
                f'</adtcore:objectReferences>').encode("utf-8")
        url = (f"{base_url(system.url)}/sap/bc/adt/activation"
               f"?method=activate&preauditRequested=true")
        try:
            resp = self._post(system, url, "application/xml", body, "application/xml")
        except httpx.HTTPError as e:
            return f"Error: activate request failed: {e}"
        if resp.status_code not in (200, 202):
            return f"Error: activate failed (HTTP {resp.status_code}): {resp.text[:200]}"
        return parse_activation(resp.content)

    def object_package(self, system: System, object_type: str,
                       name: str, function_group: str | None = None) -> str | None:
        try:
            root_url = self.object_root_url(system, object_type, name, function_group)
        except ValueError:
            return None
        try:
            resp = self._get(system, root_url, "*/*")
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or is_login_page(resp):
            return None
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return None
        for el in root.iter():
            if _localname(el.tag) == "packageRef":
                a = {_localname(k): v for k, v in el.attrib.items()}
                if a.get("name"):
                    return a["name"]
        return None

    def _edit_sequence(self, system: System, root_url: str, source_url: str,
                       source: str, transport: str | None) -> str | None:
        token = self._csrf_token(system)
        wk = self._write_kwargs(system)
        handle, err = self._lock(system, root_url, token, wk)
        if err:
            return err
        try:
            return self._put_source(system, source_url, source, handle,
                                    transport, token, wk)
        finally:
            self._unlock(system, root_url, handle, token, wk)

    def update_source(self, system: System, object_type: str, name: str,
                      source: str, transport: str | None = None,
                      function_group: str | None = None,
                      activate: bool = True) -> str:
        if not system.allow_write:
            return check_write(system, "")
        try:
            root_url = self.object_root_url(system, object_type, name, function_group)
        except ValueError as e:
            return f"Error: {e}"
        pkg = self.object_package(system, object_type, name, function_group)
        gate = check_write(system, pkg or "")
        if gate:
            return gate
        source_url = (f"{root_url}/source/main?sap-client={system.client}"
                      f"&sap-language={system.language}")
        err = self._edit_sequence(system, root_url, source_url, source, transport)
        if err:
            return err
        if activate:
            return self.activate(system, object_type, name, function_group)
        return f"OK: updated {object_type.upper()} {name.upper()} (not activated)"

    def update_class_include(self, system: System, class_name: str,
                             include: str, source: str,
                             transport: str | None = None,
                             activate: bool = True) -> str:
        inc = include.lower()
        if inc not in CLASS_INCLUDES and inc != "main":
            return (f"Error: invalid include {include!r}; valid: main, "
                    f"{', '.join(sorted(CLASS_INCLUDES))}")
        if not system.allow_write:
            return check_write(system, "")
        pkg = self.object_package(system, "CLAS", class_name)
        gate = check_write(system, pkg or "")
        if gate:
            return gate
        root_url = self.object_root_url(system, "CLAS", class_name)
        if inc == "main":
            source_url = (f"{root_url}/source/main?sap-client={system.client}"
                          f"&sap-language={system.language}")
        else:
            source_url = (f"{root_url}/includes/{inc}?sap-client={system.client}"
                          f"&sap-language={system.language}")
        err = self._edit_sequence(system, root_url, source_url, source, transport)
        if err:
            return err
        if activate:
            return self.activate(system, "CLAS", class_name)
        return f"OK: updated {class_name.upper()} include {inc} (not activated)"

    # --- Write: create (v_write Phase B) ---

    def create_object(self, system: System, object_type: str, name: str,
                      package: str, description: str = "",
                      source: str | None = None, transport: str | None = None,
                      service_definition: str | None = None,
                      binding_version: str = "V2") -> str:
        ot = OBJECT_TYPE_ALIASES.get(object_type.upper(), object_type.upper())
        if ot not in CREATE_TYPES:
            return (f"Error: cannot create type {object_type!r}; valid: "
                    f"{', '.join(CREATE_TYPES)}")
        gate = check_write(system, package)
        if gate:
            return gate
        path, root, ns, adt_type, content_type, source_capable = CREATE_TYPES[ot]
        if ot == "SRVB" and not service_definition:
            return "Error: SRVB requires service_definition"
        responsible = (system.username or "").upper() or "CB0000000000"
        body = build_creation_body(ot, name, package, description, responsible,
                                   service_definition, binding_version)
        url = f"{base_url(system.url)}{path}"
        if transport:
            url += f"?corrNr={quote(transport, safe='')}"
        try:
            resp = self._post(system, url, "application/*",
                              body.encode("utf-8"), content_type)
        except httpx.HTTPError as e:
            return f"Error: create request failed: {e}"
        if resp.status_code not in (200, 201):
            return f"Error: create failed (HTTP {resp.status_code}): {resp.text[:300]}"
        if source and source_capable:
            return self.update_source(system, ot, name, source, transport)
        return f"OK: created {ot} {name.upper()} in {package.upper()}"
