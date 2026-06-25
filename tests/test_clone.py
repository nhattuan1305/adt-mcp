from adt_mcp.adt_client import build_rename_map, rewrite_references


def test_build_rename_map_uppercases_and_suffixes():
    m = build_rename_map(["zi_fun_mf902", "ZC_FUN_MF902"], "_VN")
    assert m == {"ZI_FUN_MF902": "ZI_FUN_MF902_VN",
                 "ZC_FUN_MF902": "ZC_FUN_MF902_VN"}


def test_rewrite_reference_in_dependent_source():
    # ZC_FUN_MF902 (consumption) reads from ZI_FUN_MF902 (interface view).
    # After clone, the child must point to the _VN name of the parent.
    m = build_rename_map(["ZI_FUN_MF902", "ZC_FUN_MF902"], "_VN")
    src = "define view entity ZC_FUN_MF902 as select from ZI_FUN_MF902 { key id }"
    out = rewrite_references(src, m)
    assert "from ZI_FUN_MF902_VN" in out
    assert "ZC_FUN_MF902_VN as select" in out


def test_rewrite_leaves_external_names_untouched():
    m = build_rename_map(["ZI_FUN_MF902"], "_VN")
    src = "select from ZI_FUN_MF902 association to I_BUSINESSPARTNER"
    out = rewrite_references(src, m)
    assert "ZI_FUN_MF902_VN" in out
    assert "I_BUSINESSPARTNER" in out
    assert "I_BUSINESSPARTNER_VN" not in out


def test_rewrite_is_case_insensitive():
    m = build_rename_map(["ZI_FUN_MF902"], "_VN")
    out = rewrite_references("from zi_fun_mf902", m)
    assert out == "from ZI_FUN_MF902_VN"


def test_rewrite_longest_name_first_no_prefix_collision():
    m = build_rename_map(["ZI_FUN", "ZI_FUN_MF902"], "_VN")
    out = rewrite_references("a ZI_FUN_MF902 b ZI_FUN c", m)
    assert "ZI_FUN_MF902_VN" in out
    assert "ZI_FUN_VN c" in out
    assert "ZI_FUN_MF902_VN_VN" not in out


import httpx
from adt_mcp.adt_client import (clone_short_type, CLONE_ORDER, SKIP_CLONE_TYPES,
                                 object_root_path, ADTClient)
from adt_mcp.registry import System


def _sys(**kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="EN", auth="basic", username="u", password="p",
                cookie_file=None, cookie_string=None,
                allow_write=True, write_packages=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


def test_clone_short_type_strips_subtype():
    assert clone_short_type("DDLS/DF") == "DDLS"
    assert clone_short_type("CLAS/OC") == "CLAS"
    assert clone_short_type("srvb/svb") == "SRVB"


def test_clone_order_and_skip_sets():
    # TABL must come before DDLS; SRVD before SRVB.
    assert CLONE_ORDER.index("TABL") < CLONE_ORDER.index("DDLS")
    assert CLONE_ORDER.index("SRVD") < CLONE_ORDER.index("SRVB")
    assert "DTEL" in SKIP_CLONE_TYPES and "DOMA" in SKIP_CLONE_TYPES
    assert "SRVB" not in SKIP_CLONE_TYPES        # SRVB is cloned


def test_object_root_path_supports_srvb():
    assert object_root_path("SRVB", "zsb") == \
        "/sap/bc/adt/businessservices/bindings/ZSB"


def test_activate_many_sends_all_references_in_one_post():
    calls = {"bodies": []}

    def handler(req):
        u = str(req.url)
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if "activation" in u:
            calls["bodies"].append(req.content.decode())
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404)

    out = _client(handler).activate_many(
        _sys(), [("DDLS", "ZI_X_VN", None), ("DDLS", "ZC_X_VN", None)])
    assert out == "OK"
    assert len(calls["bodies"]) == 1
    body = calls["bodies"][0]
    assert 'adtcore:name="ZI_X_VN"' in body
    assert 'adtcore:name="ZC_X_VN"' in body


def test_activate_many_empty_is_ok():
    out = _client(lambda r: httpx.Response(404)).activate_many(_sys(), [])
    assert out == "OK"


def test_activate_many_unknown_type_returns_error():
    out = _client(lambda r: httpx.Response(200, content=b"<messages/>")).activate_many(
        _sys(), [("NOPE", "ZX", None)])
    assert out.startswith("Error:")


_NODES = (
    b'<root xmlns:adtcore="x">'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DDLS/DF</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZI_FUN_MF902</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/ddl/sources/zi_fun_mf902</OBJECT_URI>'
    b'<DESCRIPTION>iface</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DDLS/DF</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZC_FUN_MF902</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/ddl/sources/zc_fun_mf902</OBJECT_URI>'
    b'<DESCRIPTION>cons</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DOMA/DD</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZD_STATUS</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/domains/zd_status</OBJECT_URI>'
    b'<DESCRIPTION>dom</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'</root>')


def _nodestructure_handler(extra=None):
    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_NODES,
                                  headers={"content-type": "application/xml"})
        if extra:
            r = extra(req)
            if r is not None:
                return r
        return httpx.Response(404, text="nf")
    return handler


def test_clone_package_dry_run_lists_plan_and_skips_doma():
    c = _client(_nodestructure_handler())
    out = c.clone_package(_sys(), _sys(), "ZRAP_FUN_MF902",
                          "ZRAP_FUN_MF902_VN", suffix="_VN", dry_run=True)
    assert "ZI_FUN_MF902 -> ZI_FUN_MF902_VN" in out
    assert "ZC_FUN_MF902 -> ZC_FUN_MF902_VN" in out
    assert "ZD_STATUS" in out and "skip" in out.lower()
    assert "Dry run" in out


def test_clone_package_execute_rewrites_dependent_source():
    """ZC_FUN_MF902 reads from ZI_FUN_MF902; after clone, the ZC_..._VN source
    sent to SAP must contain ZI_FUN_MF902_VN (points to the clone, not original)."""
    puts = {}

    def extra(req):
        u = str(req.url)
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if req.method == "GET" and "zi_fun_mf902/source/main" in u.lower():
            return httpx.Response(200, text="define view entity ZI_FUN_MF902 "
                                  "as select from ztab { key id }")
        if req.method == "GET" and "zc_fun_mf902/source/main" in u.lower():
            return httpx.Response(200, text="define view entity ZC_FUN_MF902 "
                                  "as select from ZI_FUN_MF902 { key id }")
        if req.method == "POST" and u.endswith("/ddic/ddl/sources"):
            return httpx.Response(201, text="")
        if req.method == "GET" and "ddl/sources/" in u and "/source/main" not in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZRAP_FUN_MF902_VN"/></r>')
        if "_action=LOCK" in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>')
        if req.method == "PUT":
            puts[str(req.url)] = req.content.decode()
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return None

    c = _client(_nodestructure_handler(extra))
    out = c.clone_package(_sys(write_packages=["ZRAP_*"]),
                          _sys(write_packages=["ZRAP_*"]),
                          "ZRAP_FUN_MF902", "ZRAP_FUN_MF902_VN",
                          suffix="_VN", dry_run=False)
    body = "\n".join(puts.values())
    assert "ZI_FUN_MF902_VN" in body
    assert "from ZI_FUN_MF902 {" not in body
    assert "Clone complete" in out


# --- SRVB binding XML used by the SRVB tests ---
_BINDING_XML = (
    b'<srvb:serviceBinding xmlns:srvb="x" xmlns:adtcore="y">'
    b'<srvb:services srvb:name="ZSB_FUN">'
    b'<srvb:content srvb:version="0001">'
    b'<srvb:serviceDefinition adtcore:name="ZSD_FUN"/>'
    b'</srvb:content></srvb:services>'
    b'<srvb:binding srvb:version="V2"/>'
    b'</srvb:serviceBinding>')


def test_read_srvb_servicedef_parses_name_and_version():
    def handler(req):
        if req.method == "GET" and "bindings/" in str(req.url):
            return httpx.Response(200, content=_BINDING_XML,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(404, text="nf")

    c = _client(handler)
    sd = c._read_srvb_servicedef(
        _sys(), "/sap/bc/adt/businessservices/bindings/zsb_fun")
    assert sd == ("ZSD_FUN", "V2")


_SRVB_NODES = (
    b'<root xmlns:adtcore="x">'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>SRVB/SVB</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZSB_FUN</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/businessservices/bindings/zsb_fun</OBJECT_URI>'
    b'<DESCRIPTION>binding</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>SRVD/SRV</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZSD_FUN</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/srvd/sources/zsd_fun</OBJECT_URI>'
    b'<DESCRIPTION>svcdef</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'</root>')


def test_clone_package_execute_srvb_remaps_service_definition():
    """The SRVB clone must create a binding whose service definition is the
    _VN clone (ZSD_FUN_VN), not the original ZSD_FUN."""
    posts = {}

    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_SRVB_NODES,
                                  headers={"content-type": "application/xml"})
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        # binding read for _read_srvb_servicedef
        if req.method == "GET" and "businessservices/bindings/" in u:
            return httpx.Response(200, content=_BINDING_XML,
                                  headers={"content-type": "application/xml"})
        # SRVD source read + create + write sequence
        if req.method == "GET" and "srvd/sources/" in u and "/source/main" in u.lower():
            return httpx.Response(200, text="define service ZSD_FUN { "
                                  "expose ZI_FUN as Fun; }")
        if req.method == "GET" and "srvd/sources/" in u and "/source/main" not in u.lower():
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZRAP_FUN_MF902_VN"/></r>')
        if req.method == "POST" and u.endswith("/ddic/srvd/sources"):
            return httpx.Response(201, text="")
        if req.method == "POST" and u.endswith("/businessservices/bindings"):
            posts[u] = req.content.decode()
            return httpx.Response(201, text="")
        if "_action=LOCK" in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>')
        if req.method == "PUT":
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404, text="nf")

    c = _client(handler)
    out = c.clone_package(_sys(write_packages=["ZRAP_*"]),
                          _sys(write_packages=["ZRAP_*"]),
                          "ZRAP_FUN_MF902", "ZRAP_FUN_MF902_VN",
                          suffix="_VN", dry_run=False)
    binding_post = "\n".join(posts.values())
    assert 'adtcore:name="ZSD_FUN_VN"' in binding_post
    assert "Clone complete" in out


_CLAS_NODES = (
    b'<root xmlns:adtcore="x">'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>CLAS/OC</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZCL_FUN</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/oo/classes/zcl_fun</OBJECT_URI>'
    b'<DESCRIPTION>helper</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'</root>')


def test_clone_package_execute_clas_rewrites_includes():
    """CLAS clone reads main + include sources, rewrites references to other
    cloned names, and PUTs them to the new class."""
    puts = []

    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_CLAS_NODES,
                                  headers={"content-type": "application/xml"})
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        # class main source
        if req.method == "GET" and "classes/zcl_fun/source/main" in u.lower():
            return httpx.Response(200, text="CLASS ZCL_FUN DEFINITION. "
                                  "ENDCLASS. CLASS ZCL_FUN IMPLEMENTATION. ENDCLASS.")
        # class includes (definitions/implementations/macros/testclasses)
        if req.method == "GET" and "/includes/" in u.lower():
            return httpx.Response(200, text="* include for ZCL_FUN")
        # object_package read for the new class shell
        if req.method == "GET" and "classes/" in u.lower() \
                and "/source/main" not in u.lower() and "/includes/" not in u.lower():
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZRAP_FUN_MF902_VN"/></r>')
        if req.method == "POST" and u.endswith("/oo/classes"):
            return httpx.Response(201, text="")
        if "_action=LOCK" in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>')
        if req.method == "PUT":
            puts.append(req.content.decode())
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404, text="nf")

    c = _client(handler)
    out = c.clone_package(_sys(write_packages=["ZRAP_*"]),
                          _sys(write_packages=["ZRAP_*"]),
                          "ZRAP_FUN_MF902", "ZRAP_FUN_MF902_VN",
                          suffix="_VN", dry_run=False)
    body = "\n".join(puts)
    # main source rewritten to the _VN class name
    assert "ZCL_FUN_VN" in body
    assert "Clone complete" in out


def test_clone_package_clas_writes_main_before_testclasses():
    """Regression: a behavior class whose only non-empty include is testclasses
    (CCAU) must have its global class (main) written BEFORE the testclasses
    include — otherwise SAP rejects CCAU with 'does not have any inactive
    version'. Asserts the PUT to /source/main precedes /includes/testclasses."""
    put_targets = []

    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_CLAS_NODES,
                                  headers={"content-type": "application/xml"})
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        # source class global (main)
        if req.method == "GET" and "classes/zcl_fun/source/main" in u.lower():
            return httpx.Response(200, text="CLASS ZCL_FUN DEFINITION. ENDCLASS. "
                                  "CLASS ZCL_FUN IMPLEMENTATION. ENDCLASS.")
        # only testclasses has content; the other includes are empty -> 404
        if req.method == "GET" and "/includes/testclasses" in u.lower():
            return httpx.Response(200, text="CLASS ltc_x DEFINITION FOR TESTING.")
        if req.method == "GET" and "/includes/" in u.lower():
            return httpx.Response(404, text="nf")
        # object_package read for the new class shell
        if req.method == "GET" and "classes/" in u.lower() \
                and "/source/main" not in u.lower() and "/includes/" not in u.lower():
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZRAP_FUN_MF902_VN"/></r>')
        if req.method == "POST" and u.endswith("/oo/classes"):
            return httpx.Response(201, text="")
        if "_action=LOCK" in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>')
        if req.method == "PUT":
            put_targets.append(str(req.url).lower())
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404, text="nf")

    c = _client(handler)
    out = c.clone_package(_sys(write_packages=["ZRAP_*"]),
                          _sys(write_packages=["ZRAP_*"]),
                          "ZRAP_FUN_MF902", "ZRAP_FUN_MF902_VN",
                          suffix="_VN", dry_run=False)
    main_idx = next(i for i, t in enumerate(put_targets) if "/source/main" in t)
    tc_idx = next(i for i, t in enumerate(put_targets)
                  if "/includes/testclasses" in t)
    assert main_idx < tc_idx, \
        f"main must be written before testclasses; got {put_targets}"
    assert "Clone complete" in out


_PROG_NODES = (
    b'<root xmlns:adtcore="x">'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>PROG/P</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZPROG_FUN</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/programs/programs/zprog_fun</OBJECT_URI>'
    b'<DESCRIPTION>report</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'</root>')


def test_clone_package_dry_run_includes_prog_without_crash():
    """PROG is in CREATE_TYPES; the plan must include it without raising
    (regression: PROG was missing from CLONE_ORDER -> ValueError in sort)."""
    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_PROG_NODES,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(404, text="nf")

    c = _client(handler)
    out = c.clone_package(_sys(), _sys(), "ZRAP_FUN_MF902",
                          "ZRAP_FUN_MF902_VN", suffix="_VN", dry_run=True)
    assert "ZPROG_FUN -> ZPROG_FUN_VN" in out
    assert "Dry run" in out
