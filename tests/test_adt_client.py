import httpx
import pytest
from adt_mcp.registry import System
from adt_mcp.adt_client import ADTClient, parse_netscape_cookies


def _sys(auth="basic", **kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="JA", auth=auth, username="u", password="p",
                cookie_file=None, cookie_string=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


def test_source_url_class():
    c = ADTClient(httpx.Client())
    url = c.source_url(_sys(), "CLAS", "ZCL_X", None)
    assert url == ("https://h.example/sap/bc/adt/oo/classes/ZCL_X/"
                   "source/main?sap-client=080&sap-language=JA")


def test_source_url_fugr_requires_group():
    c = ADTClient(httpx.Client())
    with pytest.raises(ValueError):
        c.source_url(_sys(), "FUGR", "Z_FM", None)


def test_source_url_fugr():
    c = ADTClient(httpx.Client())
    url = c.source_url(_sys(), "FUGR", "Z_FM", "ZFG")
    assert ("/sap/bc/adt/functions/groups/ZFG/fmodules/Z_FM/source/main"
            in url)


def test_source_url_bad_type():
    c = ADTClient(httpx.Client())
    with pytest.raises(ValueError):
        c.source_url(_sys(), "NOPE", "X", None)


def test_get_source_ok_basic_auth():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        seen["accept"] = req.headers.get("accept")
        return httpx.Response(200, text="CLASS zcl_x.")

    body = _client(handler).get_source(_sys(), "CLAS", "ZCL_X")
    assert body == "CLASS zcl_x."
    assert seen["auth"].startswith("Basic ")
    assert seen["accept"] == "text/plain"


def test_get_source_cookie_string():
    seen = {}

    def handler(req):
        seen["cookie"] = req.headers.get("cookie")
        return httpx.Response(200, text="REPORT z.")

    s = _sys(auth="cookie", username=None, password=None,
             cookie_string="SAP_SESSIONID=abc")
    body = _client(handler).get_source(s, "PROG", "ZR")
    assert "REPORT z." == body
    assert seen["cookie"] == "SAP_SESSIONID=abc"


def test_get_source_404():
    def handler(req):
        return httpx.Response(404, text="not found")
    out = _client(handler).get_source(_sys(), "CLAS", "ZCL_X")
    assert "not found" in out.lower()


def test_get_source_401():
    def handler(req):
        return httpx.Response(401, text="unauthorized")
    out = _client(handler).get_source(_sys(), "CLAS", "ZCL_X")
    assert "auth" in out.lower()


def test_get_source_cookie_file(tmp_path):
    seen = {}

    def handler(req):
        seen["cookie"] = req.headers.get("cookie")
        return httpx.Response(200, text="X")

    # Write Netscape-format cookie file
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "h.example\tFALSE\t/\tTRUE\t0\tSAP_SESSIONID\tABC123\n",
        encoding="utf-8"
    )

    s = _sys(auth="cookie", username=None, password=None,
             cookie_string=None, cookie_file=str(cookie_file))
    body = _client(handler).get_source(s, "CLAS", "ZCL_X")
    assert body == "X"
    assert "ABC123" in seen["cookie"]


def test_parse_netscape_cookies():
    text = (
        "# Netscape HTTP Cookie File\n"
        "h.example\tFALSE\t/\tTRUE\t0\tSAP_SESSIONID\tXYZ\n"
        "h.example\tFALSE\t/\tTRUE\t0\tsap-usercontext\tsap-client=080\n"
    )
    cookies = parse_netscape_cookies(text)
    assert cookies["SAP_SESSIONID"] == "XYZ"
    assert cookies["sap-usercontext"] == "sap-client=080"


def test_get_source_saml_login_page_detected():
    def handler(req):
        return httpx.Response(
            200, html="<html><body><form><input name='SAMLRequest'></form></body></html>")
    out = _client(handler).get_source(_sys(), "CLAS", "ZCL_X")
    assert "session expired" in out.lower()


def test_test_connection_saml_login_page_detected():
    def handler(req):
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"},
            text="<html>login</html>")
    out = _client(handler).test_connection(_sys())
    assert "session expired" in out.lower()


def test_test_connection_real_ok_not_flagged():
    def handler(req):
        return httpx.Response(
            200, headers={"content-type": "application/atomsvc+xml"},
            text="<app:service/>")
    assert _client(handler).test_connection(_sys()) == "OK"


def test_base_url_strips_path_and_fragment():
    from adt_mcp.adt_client import base_url
    assert base_url("https://h.example/ui#Shell-home") == "https://h.example"
    assert base_url("https://h.example") == "https://h.example"
    assert base_url("h.example:44300") == "https://h.example:44300"


def test_source_url_with_launchpad_url():
    c = ADTClient(httpx.Client())
    s = _sys(url="https://h.example/ui#Shell-home")
    url = c.source_url(s, "CLAS", "ZCL_X", None)
    assert url.startswith("https://h.example/sap/bc/adt/oo/classes/ZCL_X/source/main")
    assert "#" not in url.split("?")[0]


# --- v2 Phase 1 ---
from adt_mcp.adt_client import (parse_nodestructure, parse_search,
                                extract_method, list_method_decls)

NODES_XML = b"""<?xml version="1.0"?>
<asx:abap xmlns:asx="x"><asx:values><DATA><TREE_CONTENT>
<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>CLAS/OC</OBJECT_TYPE>
<OBJECT_NAME>ZCL_A</OBJECT_NAME>
<OBJECT_URI>/sap/bc/adt/oo/classes/zcl_a</OBJECT_URI>
<DESCRIPTION>Demo</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>
<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DEVC/K</OBJECT_TYPE>
<OBJECT_NAME>ZSUB</OBJECT_NAME><OBJECT_URI>/sap/bc/adt/packages/zsub</OBJECT_URI>
<DESCRIPTION>sub</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>
</TREE_CONTENT></DATA></asx:values></asx:abap>"""

SEARCH_XML = b"""<?xml version="1.0"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
<adtcore:objectReference adtcore:name="ZCL_X" adtcore:type="CLAS/OC"
 adtcore:uri="/sap/bc/adt/oo/classes/zcl_x" adtcore:packageName="ZP"/>
</adtcore:objectReferences>"""


def test_parse_nodestructure():
    objs = parse_nodestructure(NODES_XML)
    assert {o["name"] for o in objs} == {"ZCL_A", "ZSUB"}
    a = next(o for o in objs if o["name"] == "ZCL_A")
    assert a["type"] == "CLAS/OC" and a["uri"].endswith("zcl_a")


def test_parse_search():
    objs = parse_search(SEARCH_XML)
    assert objs[0]["name"] == "ZCL_X"
    assert objs[0]["type"] == "CLAS/OC"
    assert objs[0]["package"] == "ZP"


def test_extract_method():
    src = ("CLASS x.\nMETHOD foo.\n  WRITE 1.\nENDMETHOD.\n"
           "METHOD bar.\n  WRITE 2.\nENDMETHOD.\n")
    blk = extract_method(src, "FOO")
    assert blk.startswith("METHOD foo.") and blk.strip().endswith("ENDMETHOD.")
    assert "WRITE 2" not in blk
    assert extract_method(src, "NOPE") is None


def test_list_method_decls():
    src = ("CLASS-METHODS create.\n  METHODS do_it.\nDATA x.\n"
           "  methods Do_It.\n")
    assert list_method_decls(src) == ["CREATE", "DO_IT"]


def test_source_url_extended_types():
    c = ADTClient(httpx.Client())
    assert "/ddic/ddl/sources/ZDDL/source/main" in \
        c.source_url(_sys(), "DDLS", "ZDDL", None)
    assert "/bo/behaviordefinitions/ZBD/source/main" in \
        c.source_url(_sys(), "BDEF", "ZBD", None)
    assert "/ddic/structures/ZS/source/main" in \
        c.source_url(_sys(), "STRUCT", "ZS", None)


def test_get_source_by_uri_appends_source_main():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        return httpx.Response(200, text="SRC")

    out = _client(handler).get_source_by_uri(_sys(), "/sap/bc/adt/oo/classes/zcl_a")
    assert out == "SRC"
    assert seen["path"].endswith("/zcl_a/source/main")


def test_get_class_include_invalid():
    out = ADTClient(httpx.Client()).get_class_include(_sys(), "ZCL", "bogus")
    assert "invalid include" in out.lower()


def test_grep_package():
    def handler(req):
        if "nodestructure" in req.url.path:
            return httpx.Response(200, content=NODES_XML,
                                  headers={"content-type": "application/xml"})
        # object source
        return httpx.Response(200, text="line one\nFOO here\nlast")

    out = _client(handler).grep_package(_sys(), "ZP", "FOO")
    assert "ZCL_A:2: FOO here" in out


def test_get_package_source():
    def handler(req):
        if "nodestructure" in req.url.path:
            return httpx.Response(200, content=NODES_XML,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(200, text="CLASS body")

    out = _client(handler).get_package_source(_sys(), "ZP")
    assert "==== CLAS/OC ZCL_A ====" in out
    assert "CLASS body" in out


# Three source objects; parallel fetch must keep package order in the output.
NODES_XML_3 = b"""<?xml version="1.0"?>
<asx:abap xmlns:asx="x"><asx:values><DATA><TREE_CONTENT>
<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>CLAS/OC</OBJECT_TYPE>
<OBJECT_NAME>ZCL_A</OBJECT_NAME>
<OBJECT_URI>/sap/bc/adt/oo/classes/zcl_a</OBJECT_URI></SEU_ADT_REPOSITORY_OBJ_NODE>
<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>CLAS/OC</OBJECT_TYPE>
<OBJECT_NAME>ZCL_B</OBJECT_NAME>
<OBJECT_URI>/sap/bc/adt/oo/classes/zcl_b</OBJECT_URI></SEU_ADT_REPOSITORY_OBJ_NODE>
<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>CLAS/OC</OBJECT_TYPE>
<OBJECT_NAME>ZCL_C</OBJECT_NAME>
<OBJECT_URI>/sap/bc/adt/oo/classes/zcl_c</OBJECT_URI></SEU_ADT_REPOSITORY_OBJ_NODE>
</TREE_CONTENT></DATA></asx:values></asx:abap>"""


def test_get_package_source_preserves_order():
    import time

    def handler(req):
        if "nodestructure" in req.url.path:
            return httpx.Response(200, content=NODES_XML_3,
                                  headers={"content-type": "application/xml"})
        # zcl_a fetch sleeps longest; if fetched in parallel and output is
        # still A,B,C then ordering is preserved regardless of completion order.
        name = req.url.path.rsplit("/", 2)[-2]
        if name == "zcl_a":
            time.sleep(0.05)
        return httpx.Response(200, text=f"body of {name}")

    out = _client(handler).get_package_source(_sys(), "ZP")
    assert out.index("ZCL_A") < out.index("ZCL_B") < out.index("ZCL_C")


# --- v2 Phase 2: revisions/diff ---
from adt_mcp.adt_client import parse_revision_feed, revision_url

REV_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:adtcore="http://www.sap.com/adt/core">
<entry><id>v2</id><title>2</title><updated>2026-06-01T10:00:00Z</updated>
<author><name>TESTUSER</name></author>
<content src="/sap/bc/adt/oo/classes/zcl_a/includes/main/versions/2/content"/>
<link type="application/.../transportrequests" adtcore:name="TR-1"/></entry>
<entry><id>v1</id><title>1</title><updated>2026-05-01T10:00:00Z</updated>
<author><name>TESTUSER</name></author>
<content src="/sap/bc/adt/oo/classes/zcl_a/includes/main/versions/1/content"/></entry>
</feed>"""


def test_parse_revision_feed():
    revs = parse_revision_feed(REV_XML)
    assert len(revs) == 2
    assert revs[0]["author"] == "TESTUSER"
    assert revs[0]["transport"] == "TR-1"
    assert revs[0]["uri"].endswith("/2/content")
    assert revs[1]["transport"] == ""


def test_revision_url():
    assert revision_url("PROG", "ZR").endswith("/programs/ZR/source/main/versions")
    assert "/oo/classes/ZCL_A/includes/main/versions" in revision_url("CLAS", "zcl_a")
    assert "/includes/definitions/versions" in revision_url("CLAS", "ZC", include="definitions")
    assert "/fmodules/ZFM/source/main/versions" in revision_url("FUNC", "ZFM", function_group="ZFG")


def test_revision_url_func_requires_group():
    import pytest as _pt
    with _pt.raises(ValueError):
        revision_url("FUNC", "ZFM")


def test_get_revisions_and_compare():
    def handler(req):
        p = req.url.path
        if p.endswith("/versions"):
            return httpx.Response(200, content=REV_XML,
                                  headers={"content-type": "application/atom+xml"})
        if "/versions/2/content" in p:
            return httpx.Response(200, text="line A\nline B\n")
        if "/versions/1/content" in p:
            return httpx.Response(200, text="line A\nOLD\n")
        # current source
        return httpx.Response(200, text="line A\nline B\n")

    c = _client(handler)
    revs = c.get_revisions(_sys(), "CLAS", "ZCL_A")
    assert len(revs) == 2 and revs[0]["transport"] == "TR-1"
    # compare v1 vs current → differs
    d = c.compare_source(_sys(), "CLAS", "ZCL_A",
                         "/sap/bc/adt/oo/classes/zcl_a/includes/main/versions/1/content")
    assert "OLD" in d and "line B" in d


# --- v2 Phase 3: where-used ---
from adt_mcp.adt_client import parse_usage_references

USAGE_XML = b"""<?xml version="1.0"?>
<usageReferences:usageReferenceResult
 xmlns:usageReferences="http://www.sap.com/adt/ris/usageReferences"
 xmlns:adtcore="http://www.sap.com/adt/core">
<usageReferences:referencedObjects>
<usageReferences:referencedObject uri="/sap/bc/adt/oo/classes/zbp_r"
 usageInformation="1">
  <usageReferences:adtObject adtcore:name="ZBP_R" adtcore:type="CLAS/OC"
   adtcore:description="BP">
    <usageReferences:packageRef adtcore:name="ZPKG"/>
  </usageReferences:adtObject>
</usageReferences:referencedObject>
</usageReferences:referencedObjects>
</usageReferences:usageReferenceResult>"""


def test_parse_usage_references():
    refs = parse_usage_references(USAGE_XML)
    assert len(refs) == 1
    assert refs[0]["name"] == "ZBP_R"
    assert refs[0]["type"] == "CLAS/OC"
    assert refs[0]["package"] == "ZPKG"


def test_find_references_uri_and_position():
    seen = {}

    def handler(req):
        if "usageReferences" in req.url.path or "usageReferences" in str(req.url):
            seen["url"] = str(req.url)
            return httpx.Response(200, content=USAGE_XML,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(200, text="")  # csrf fetch

    c = _client(handler)
    res = c.find_references(_sys(), "/sap/bc/adt/oo/classes/zcl_a", 12, 5)
    assert isinstance(res, list) and res[0]["name"] == "ZBP_R"
    assert "start%3D12%2C5" in seen["url"] or "start=12,5" in seen["url"]


# --- v2 Phase 4: CDS deps ---
from adt_mcp.adt_client import parse_cds_dependencies


def test_parse_cds_dependencies():
    src = ("define root view entity ZR as select from z039_anhht\n"
           "  association [0..1] to I_ProductText as _p on _p.x = $projection.x\n"
           "  composition [0..*] of ZC_Item as _item\n"
           "{ key x }\n")
    deps = parse_cds_dependencies(src)
    rels = {(d["relation"], d["name"]) for d in deps}
    assert ("FROM", "z039_anhht") in rels
    assert ("ASSOCIATION", "I_ProductText") in rels
    assert ("COMPOSITION", "ZC_Item") in rels


def test_parse_cds_dependencies_join():
    src = "select from a inner join b on a.k = b.k"
    rels = {(d["relation"], d["name"]) for d in parse_cds_dependencies(src)}
    assert ("FROM", "a") in rels and ("JOIN", "b") in rels


# --- syntax check (ABAP check run) ---
from adt_mcp.adt_client import parse_check_run


def test_parse_check_run():
    data = (b'<?xml version="1.0"?>'
            b'<chkrun:checkRunReports '
            b'xmlns:chkrun="http://www.sap.com/adt/checkrun">'
            b'<chkrun:checkReport chkrun:reporter="abapCheckRun">'
            b'<chkrun:checkMessageList>'
            b'<chkrun:checkMessage chkrun:type="E" '
            b'chkrun:shortText="Field FOO is unknown" '
            b'chkrun:uri="/sap/bc/adt/oo/classes/ZCL/source/main#start=12,3"/>'
            b'<chkrun:checkMessage chkrun:type="W" '
            b'chkrun:shortText="Variable BAR not used" '
            b'chkrun:uri="/x#start=20,1"/>'
            b'</chkrun:checkMessageList>'
            b'</chkrun:checkReport>'
            b'</chkrun:checkRunReports>')
    msgs = parse_check_run(data)
    assert len(msgs) == 2
    assert msgs[0]["type"] == "E"
    assert msgs[0]["line"] == "12"
    assert msgs[0]["text"] == "Field FOO is unknown"
    assert msgs[1]["type"] == "W"


def test_parse_check_run_empty():
    assert parse_check_run(b"") == []


# --- API release state ---
from adt_mcp.adt_client import parse_release_state


def test_parse_release_state_released():
    xml = (b'<?xml version="1.0"?><apiRelease>'
           b'<releasableObject uri="/sap/bc/adt/oo/classes/cl_x" '
           b'type="CLAS" name="CL_X"/>'
           b'<c1Release contract="C1" useInKeyUserApps="false" '
           b'useInSAPCloudPlatform="true" name="CL_X">'
           b'<status state="RELEASED" stateDescription="Released"/>'
           b'</c1Release>'
           b'<apiCatalogData isAnyAssignmentPossible="true" '
           b'isAnyContractReleased="true"/></apiRelease>')
    st = parse_release_state(xml)
    assert st["object"]["name"] == "CL_X"
    assert st["anyContractReleased"] is True
    c1 = st["contracts"][0]
    assert c1["contract"] == "C1"
    assert c1["state"] == "RELEASED"
    assert c1["cloud"] is True
    assert c1["keyUser"] is False


def test_parse_release_state_deprecated_with_successor():
    xml = (b'<apiRelease>'
           b'<releasableObject type="CLAS" name="CL_OLD"/>'
           b'<c1Release contract="C1" useInSAPCloudPlatform="true">'
           b'<status state="DEPRECATED" stateDescription="Deprecated"/>'
           b'<successors><successor name="CL_NEW"/></successors>'
           b'</c1Release></apiRelease>')
    st = parse_release_state(xml)
    c1 = st["contracts"][0]
    assert c1["state"] == "DEPRECATED"
    assert c1["successors"] == ["CL_NEW"]


def test_parse_release_state_empty():
    assert parse_release_state(b"")["contracts"] == []


def test_parse_release_state_ignores_state_transitions():
    # Real ABAP Cloud apirelease.v10 shape (e.g. BDEF I_SALESORDERTP): a
    # contract carries its own <status> AND a <stateTransitions> block listing
    # the allowed *next* states as further <status> elements. The parser must
    # read only the contract's own status, not the last transition option.
    xml = (b'<ars:apiRelease xmlns:ars="http://www.sap.com/adt/ars">'
           b'<ars:releasableObject xmlns:adtcore="http://www.sap.com/adt/core"'
           b' adtcore:type="BDEF/BDO" adtcore:name="I_SALESORDERTP"/>'
           b'<ars:behaviour ars:create="false">'
           b'<ars:c0Release ars:read="true"'
           b' ars:useInSAPCloudPlatformDefault="true"/>'
           b'</ars:behaviour>'
           b'<ars:c0Release ars:contract="C0" ars:useInSAPCloudPlatform="true"'
           b' ars:useInKeyUserApps="false">'
           b'<ars:status ars:state="RELEASED" ars:stateDescription="Released"/>'
           b'<ars:stateTransitions>'
           b'<ars:status ars:state="RELEASED" ars:stateDescription="Released"/>'
           b'<ars:status ars:state="NOT_RELEASED"'
           b' ars:stateDescription="Not Released"/>'
           b'</ars:stateTransitions>'
           b'</ars:c0Release></ars:apiRelease>')
    st = parse_release_state(xml)
    contracts = [c for c in st["contracts"] if c["state"]]
    assert len(contracts) == 1
    assert contracts[0]["contract"] == "C0"
    assert contracts[0]["state"] == "RELEASED"
    assert contracts[0]["cloud"] is True
    assert contracts[0]["keyUser"] is False


# --- v2 Phase 6: context compression ---
from adt_mcp.adt_client import compress_source


def test_compress_source_ddls_strips_annotations():
    src = ("@AccessControl.authorizationCheck: #CHECK\n"
           "// a comment\n"
           "define view entity ZI as select from t {\n  key a }\n")
    out = compress_source("DDLS", src)
    assert "@AccessControl" not in out and "// a comment" not in out
    assert "define view entity ZI" in out and "key a" in out


def test_compress_source_clas_drops_implementation():
    src = ("CLASS zcl DEFINITION PUBLIC.\n  PUBLIC SECTION.\n"
           "    METHODS m.\nENDCLASS.\n"
           "CLASS zcl IMPLEMENTATION.\n  METHOD m.\n    secret.\nENDMETHOD.\nENDCLASS.\n")
    out = compress_source("CLAS", src)
    assert "PUBLIC SECTION" in out and "METHODS m" in out
    assert "secret" not in out


def test_get_context_cds_chain():
    def handler(req):
        p = str(req.url)
        if "ddl/sources/ZC" in p:
            return httpx.Response(200, text=(
                "@EndUserText.label: 'C'\n"
                "define view entity ZC as projection on ZR { key a }\n"))
        if "ddl/sources/ZR" in p:
            return httpx.Response(200, text=(
                "@EndUserText.label: 'R'\n"
                "define root view entity ZR as select from ztab { key a }\n"))
        if "ddic/tables/ZTAB" in p:
            return httpx.Response(200, text="define table ztab { key a : abap.char(1); }")
        return httpx.Response(404, text="nf")

    out = _client(handler).get_context(_sys(), "DDLS", "ZC", depth=2)
    assert "(full source)" in out
    assert "ASSOCIATION" not in out  # ZC uses projection on -> FROM not assoc here
    assert "ZR" in out and "ztab" in out.lower()
    # compressed deps drop annotations
    assert "@EndUserText.label: 'R'" not in out


# --- get_context for BDEF / CLAS (fix 6) ---
from adt_mcp.adt_client import (parse_bdef_dependencies,
                                parse_class_dependencies)


def test_parse_bdef_dependencies():
    src = ("managed implementation in class zbp_r_travel unique;\n"
           "define behavior for ZR_Travel alias Travel\n"
           "persistent table ztravel\n{ ... }\n")
    d = parse_bdef_dependencies(src)
    assert d["entities"] == ["ZR_Travel"]
    assert d["classes"] == ["zbp_r_travel"]


def test_parse_class_dependencies():
    src = ("CLASS zcl_x DEFINITION PUBLIC INHERITING FROM zcl_base.\n"
           "  PUBLIC SECTION.\n"
           "    INTERFACES zif_a.\n"
           "    INTERFACES if_oo_adt_classrun.\n")
    d = parse_class_dependencies(src)
    assert d["superclass"] == "zcl_base"
    assert "zif_a" in d["interfaces"]
    assert "if_oo_adt_classrun" in d["interfaces"]


def test_get_context_bdef():
    def handler(req):
        p = str(req.url).upper()
        if "BEHAVIORDEFINITIONS/ZR_TRAVEL" in p:
            return httpx.Response(200, text=(
                "managed implementation in class zbp_r_travel unique;\n"
                "define behavior for ZR_Travel alias Travel\n"))
        if "DDL/SOURCES/ZR_TRAVEL" in p:
            return httpx.Response(200, text=(
                "@EndUserText.label: 'T'\n"
                "define root view entity ZR_Travel as select from ztravel "
                "{ key id }\n"))
        if "TABLES/ZTRAVEL" in p:
            return httpx.Response(
                200, text="define table ztravel { key id : abap.int4; }")
        if "OO/CLASSES/ZBP_R_TRAVEL" in p:
            return httpx.Response(200, text=(
                "CLASS zbp_r_travel DEFINITION PUBLIC.\n  PUBLIC SECTION.\n"
                "ENDCLASS.\nCLASS zbp_r_travel IMPLEMENTATION.\n"
                "  METHOD m.\n    secret_logic.\n  ENDMETHOD.\nENDCLASS.\n"))
        return httpx.Response(404, text="nf")

    out = _client(handler).get_context(_sys(), "BDEF", "ZR_TRAVEL", depth=1)
    assert "(full source)" in out
    assert "ZR_Travel" in out               # behavior-for CDS pulled in
    assert "ztravel" in out.lower()         # CDS dep (table) expanded
    assert "zbp_r_travel" in out.lower()    # impl class pulled in
    assert "secret_logic" not in out        # impl class compressed to defs


def test_get_context_clas():
    def handler(req):
        p = str(req.url).upper()
        if "OO/CLASSES/ZCL_X/SOURCE" in p:
            return httpx.Response(200, text=(
                "CLASS zcl_x DEFINITION PUBLIC INHERITING FROM zcl_base.\n"
                "  PUBLIC SECTION.\n    INTERFACES zif_a.\n"
                "    INTERFACES if_oo_adt_classrun.\nENDCLASS.\n"))
        if "OO/CLASSES/ZCL_BASE/SOURCE" in p:
            return httpx.Response(200, text=(
                "CLASS zcl_base DEFINITION PUBLIC.\n  PUBLIC SECTION.\n"
                "ENDCLASS.\nCLASS zcl_base IMPLEMENTATION.\n"
                "  METHOD b.\n    base_secret.\n  ENDMETHOD.\nENDCLASS.\n"))
        if "OO/INTERFACES/ZIF_A/SOURCE" in p:
            return httpx.Response(200, text=(
                "INTERFACE zif_a PUBLIC.\n  METHODS do.\nENDINTERFACE.\n"))
        return httpx.Response(404, text="nf")

    out = _client(handler).get_context(_sys(), "CLAS", "ZCL_X")
    assert "(full source)" in out
    assert "zcl_base" in out.lower()        # superclass pulled in, compressed
    assert "base_secret" not in out
    assert "zif_a" in out.lower()           # custom interface pulled in
    assert "if_oo_adt_classrun" in out.lower()  # standard listed, not expanded


# --- ABAP Unit test run ---
from adt_mcp.adt_client import parse_aunit_result

AUNIT_XML = b"""<?xml version="1.0"?>
<aunit:runResult xmlns:aunit="http://www.sap.com/adt/aunit"
 xmlns:adtcore="http://www.sap.com/adt/core">
<program adtcore:name="ZCL_X" adtcore:type="CLAS/OC"><testClasses>
<testClass adtcore:name="LTCL_MAIN"><testMethods>
<testMethod adtcore:name="TEST_PASS" executionTime="0.01"/>
<testMethod adtcore:name="TEST_FAIL" executionTime="0.02"><alerts>
<alert kind="failedAssertion" severity="critical">
<title>Assertion failed</title>
<details><detail text="Expected 1 but was 2"/></details>
</alert></alerts></testMethod>
</testMethods></testClass></testClasses></program></aunit:runResult>"""


def test_parse_aunit_result():
    methods = parse_aunit_result(AUNIT_XML)
    assert len(methods) == 2
    p = next(m for m in methods if m["method"] == "TEST_PASS")
    f = next(m for m in methods if m["method"] == "TEST_FAIL")
    assert p["class"] == "LTCL_MAIN" and p["alerts"] == []
    assert f["alerts"][0]["severity"] == "critical"
    assert f["alerts"][0]["title"] == "Assertion failed"
    assert "Expected 1 but was 2" in f["alerts"][0]["details"]


def test_parse_aunit_result_empty():
    assert parse_aunit_result(b"") == []


def test_run_unit_tests_ok():
    seen = {}

    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if "abapunit/testruns" in u:
            seen["body"] = req.content.decode()
            seen["accept"] = req.headers.get("accept")
            return httpx.Response(200, content=AUNIT_XML,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(404)

    out = _client(handler).run_unit_tests(_sys(), "CLAS", "ZCL_X")
    assert "1 failed" in out
    assert "TEST_FAIL" in out and "TEST_PASS" in out
    assert "Expected 1 but was 2" in out
    assert "/sap/bc/adt/oo/classes/ZCL_X" in seen["body"]
    # ADT requires this exact result content type (else HTTP 406)
    assert seen["accept"] == \
        "application/vnd.sap.adt.abapunit.testruns.result.v2+xml"


def test_run_unit_tests_none():
    def handler(req):
        if "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        return httpx.Response(200, content=b'<aunit:runResult xmlns:aunit="x"/>',
                              headers={"content-type": "application/xml"})
    out = _client(handler).run_unit_tests(_sys(), "CLAS", "ZCL_X")
    assert "no abap unit" in out.lower()


# --- Data preview (CDS / SQL) ---
from adt_mcp.adt_client import parse_data_preview

PREVIEW_XML = b"""<?xml version="1.0"?>
<dataPreview:tableData xmlns:dataPreview="http://www.sap.com/adt/datapreview">
<dataPreview:totalRows>2</dataPreview:totalRows>
<dataPreview:columns>
<dataPreview:metadata dataPreview:name="ID" dataPreview:type="C"/>
<dataPreview:dataSet>
<dataPreview:data>1</dataPreview:data>
<dataPreview:data>2</dataPreview:data>
</dataPreview:dataSet></dataPreview:columns>
<dataPreview:columns>
<dataPreview:metadata dataPreview:name="NAME" dataPreview:type="C"/>
<dataPreview:dataSet>
<dataPreview:data>Alice</dataPreview:data>
<dataPreview:data>Bob</dataPreview:data>
</dataPreview:dataSet></dataPreview:columns>
</dataPreview:tableData>"""


def test_parse_data_preview():
    res = parse_data_preview(PREVIEW_XML)
    assert res["columns"] == ["ID", "NAME"]
    assert res["rows"] == [["1", "Alice"], ["2", "Bob"]]
    assert res["total"] == 2


def test_data_preview_wraps_bare_entity():
    seen = {}

    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if "datapreview/freestyle" in u:
            seen["body"] = req.content.decode()
            seen["url"] = u
            seen["accept"] = req.headers.get("accept")
            return httpx.Response(200, content=PREVIEW_XML,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(404)

    out = _client(handler).data_preview(_sys(), "ZI_X", max_rows=50)
    assert "SELECT * FROM ZI_X" in seen["body"].upper()
    assert "rowNumber=50" in seen["url"]
    assert seen["accept"] == "application/vnd.sap.adt.datapreview.table.v1+xml"
    assert "ID" in out and "NAME" in out
    assert "Alice" in out and "Bob" in out


def test_data_preview_passes_full_select():
    seen = {}

    def handler(req):
        if "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        seen["body"] = req.content.decode()
        return httpx.Response(200, content=PREVIEW_XML,
                              headers={"content-type": "application/xml"})

    _client(handler).data_preview(_sys(), "SELECT id FROM zi_x WHERE id = 1")
    assert seen["body"].strip().upper().startswith("SELECT ID FROM ZI_X")


# --- ABAP Profiler (runtime traces) ---
from adt_mcp.adt_client import (parse_trace_runs, parse_trace_hitlist,
                                parse_trace_dbaccesses)

TRACE_FEED = b"""<?xml version="1.0"?>
<atom:feed xmlns:atom="http://www.w3.org/2005/Atom"
 xmlns:trc="http://www.sap.com/adt/runtime/traces/abaptraces">
<atom:entry><atom:author><atom:name>CB99</atom:name></atom:author>
<atom:id>/sap/bc/adt/runtime/traces/abaptraces/7E03</atom:id>
<atom:title>AIPROBE</atom:title><atom:published>2026-06-21T03:15:45Z</atom:published>
<trc:extendedData><trc:runtime>325516</trc:runtime>
<trc:runtimeABAP>23785</trc:runtimeABAP><trc:runtimeDatabase>301580</trc:runtimeDatabase>
<trc:state value="R" text="Finished"/></trc:extendedData></atom:entry>
</atom:feed>"""

TRACE_HITLIST = b"""<?xml version="1.0"?>
<trc:hitlist xmlns:trc="http://www.sap.com/adt/runtime/traces/abaptraces"
 xmlns:adtcore="http://www.sap.com/adt/core">
<trc:entry topDownIndex="1" hitCount="1" description="DB: Prepare TATRAPI_FILES2">
<trc:callingProgram adtcore:type="FUGR/FF" adtcore:name="ATRA_GET_FILE_DIR"/>
<trc:grossTime time="26084" percentage="26.208"/>
<trc:traceEventNetTime time="26084" percentage="26.208"/></trc:entry>
<trc:entry topDownIndex="2" hitCount="1" description="Runtime Analysis On">
<trc:callingProgram adtcore:name="SAPLHTTP_RUNTIME"/>
<trc:grossTime time="100" percentage="0.1"/>
<trc:traceEventNetTime time="100" percentage="0.1"/></trc:entry>
</trc:hitlist>"""

TRACE_DBACCESS = b"""<?xml version="1.0"?>
<trc:dbAccesses totalDbTime="10394"
 xmlns:trc="http://www.sap.com/adt/runtime/traces/abaptraces"
 xmlns:adtcore="http://www.sap.com/adt/core">
<trc:dbAccess index="2" tableName="SADT_BADI_ACCESS" statement="select"
 type="OpenSQL" totalCount="3" bufferedCount="1">
<trc:accessTime total="71" database="71" ratioOfTraceTotal="0.1"/>
<trc:callingProgram adtcore:name="CL_ADT_SAFE_MODE_BADI_ACCESS"/></trc:dbAccess>
<trc:dbAccess index="3" tableName="TOBJ_CHK_CTRL_DH" statement="select single"
 type="OpenSQL" totalCount="1" bufferedCount="0">
<trc:accessTime total="48" database="48" ratioOfTraceTotal="0.0"/></trc:dbAccess>
</trc:dbAccesses>"""


def test_parse_trace_runs():
    runs = parse_trace_runs(TRACE_FEED)
    assert len(runs) == 1
    r = runs[0]
    assert r["uri"] == "/sap/bc/adt/runtime/traces/abaptraces/7E03"
    assert r["title"] == "AIPROBE"
    assert r["runtime"] == 325516 and r["runtime_db"] == 301580
    assert r["state"] == "Finished"


def test_parse_trace_hitlist():
    h = parse_trace_hitlist(TRACE_HITLIST)
    assert len(h) == 2
    assert h[0]["description"] == "DB: Prepare TATRAPI_FILES2"
    assert h[0]["gross_pct"] == 26.208
    assert h[0]["gross_time"] == 26084
    assert h[0]["program"] == "ATRA_GET_FILE_DIR"


def test_parse_trace_dbaccesses():
    db = parse_trace_dbaccesses(TRACE_DBACCESS)
    assert db["total_db_time"] == 10394
    assert len(db["accesses"]) == 2
    a = db["accesses"][0]
    assert a["table"] == "SADT_BADI_ACCESS"
    assert a["statement"] == "select"
    assert a["total_count"] == 3 and a["buffered_count"] == 1
    assert a["db_time"] == 71


def test_trace_start_posts_params_then_request():
    seen = {}

    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if u.endswith("/parameters") and req.method == "POST":
            seen["params_body"] = req.content.decode()
            return httpx.Response(200, headers={
                "location": "/sap/bc/adt/runtime/traces/abaptraces/parameters/PID1"})
        if "/requests" in u and req.method == "POST":
            seen["req_url"] = u
            return httpx.Response(200, content=b'<atom:feed xmlns:atom="x"/>')
        return httpx.Response(404)

    out = _client(handler).trace_start(_sys(), process_type="http",
                                       max_executions=2)
    assert "allProceduralUnits" in seen["params_body"]
    assert "parametersId=" in seen["req_url"] and "PID1" in seen["req_url"]
    assert "processtypes%2Fhttp" in seen["req_url"]   # url-encoded path
    assert "maximalExecutions=2" in seen["req_url"]
    assert "ok" in out.lower() or "trace" in out.lower()


def test_trace_list_no_user_param():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, content=TRACE_FEED,
                              headers={"content-type": "application/atom+xml"})

    out = _client(handler).trace_list(_sys())
    assert "user=" not in seen["url"]          # defaults to caller
    assert "AIPROBE" in out
    assert "301580" in out or "301" in out     # db runtime surfaced


TRACE_FEED_2 = b"""<?xml version="1.0"?>
<atom:feed xmlns:atom="http://www.w3.org/2005/Atom"
 xmlns:trc="http://www.sap.com/adt/runtime/traces/abaptraces">
<atom:entry><atom:id>/sap/bc/adt/runtime/traces/abaptraces/OLD</atom:id>
<atom:title>old</atom:title><atom:published>2026-06-21T03:00:00Z</atom:published>
<trc:extendedData><trc:state value="R" text="Finished"/></trc:extendedData></atom:entry>
<atom:entry><atom:id>/sap/bc/adt/runtime/traces/abaptraces/NEW</atom:id>
<atom:title>new</atom:title><atom:published>2026-06-21T05:00:00Z</atom:published>
<trc:extendedData><trc:state value="R" text="Finished"/></trc:extendedData></atom:entry>
</atom:feed>"""


def test_trace_list_newest_first():
    out = _client(lambda r: httpx.Response(
        200, content=TRACE_FEED_2,
        headers={"content-type": "application/atom+xml"})).trace_list(_sys())
    assert out.index("/NEW") < out.index("/OLD")  # newest run listed first


def test_trace_analyze_db_total_fallback():
    # totalDbTime="0" → header sums the per-access db times (71 + 48 = 119)
    def handler(req):
        u = str(req.url)
        if "/hitlist" in u:
            return httpx.Response(200, content=TRACE_HITLIST)
        return httpx.Response(200, content=TRACE_DBACCESS.replace(
            b'totalDbTime="10394"', b'totalDbTime="0"'))
    out = _client(handler).trace_analyze(_sys(), "/x")
    assert "total 0.1ms" in out  # (71+48)/1000 = 0.119 -> 0.1


def test_trace_analyze_combines_hitlist_and_db():
    def handler(req):
        u = str(req.url)
        if u.endswith("/hitlist") or "/hitlist?" in u:
            return httpx.Response(200, content=TRACE_HITLIST,
                                  headers={"content-type": "application/xml"})
        if "/dbAccesses" in u:
            return httpx.Response(200, content=TRACE_DBACCESS,
                                  headers={"content-type": "application/xml"})
        return httpx.Response(404)

    out = _client(handler).trace_analyze(
        _sys(), "/sap/bc/adt/runtime/traces/abaptraces/7E03")
    assert "DB: Prepare TATRAPI_FILES2" in out   # hitlist
    assert "26.2" in out
    assert "SADT_BADI_ACCESS" in out             # db accesses
    assert "TOBJ_CHK_CTRL_DH" in out


from adt_mcp.adt_client import parse_dumps_feed, html_to_text

# Mirrors the real S/4 Public Cloud feed: atom:id is a logical 'vit' key, the
# atom:link hrefs are adt:// SAP GUI links (not HTTP), and the full dump HTML is
# embedded (escaped) in atom:summary.
_DUMP_ID = ("/sap/bc/adt/vit/runtime/dumps/20260620111213host_NWF_00"
            "%20%20%20CB99%2089")
DUMPS_FEED = ("""<?xml version="1.0" encoding="utf-8"?>
<atom:feed xmlns:atom="http://www.w3.org/2005/Atom">
<atom:entry>
<atom:author><atom:name>CB99</atom:name></atom:author>
<atom:category term="UNCAUGHT_EXCEPTION" label="ABAP runtime error"/>
<atom:category term="ZCL_ORDER============CP" label="Terminated ABAP program"/>
<atom:id>""" + _DUMP_ID + """</atom:id>
<atom:link href="adt://NWF/sap/bc/adt/vit/runtime/dumps/x" rel="alternate" type="application/vnd.sap.adt.sapgui"/>
<atom:link href="adt://NWF/sap/bc/adt/runtime/dump/x" rel="self" type="text/plain"/>
<atom:summary type="html">&lt;h4&gt;Error analysis&lt;/h4&gt;Division&amp;nbsp;by&amp;nbsp;zero&lt;br&gt;CX_SY_ZERODIVIDE&lt;table&gt;&lt;tr&gt;&lt;td&gt;POST&lt;/td&gt;&lt;td&gt;42&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</atom:summary>
<atom:title>The exception CX_SY_ZERODIVIDE was raised.</atom:title>
<atom:updated>2026-06-20T11:12:13Z</atom:updated>
</atom:entry>
<atom:entry>
<atom:author><atom:name>MILLER</atom:name></atom:author>
<atom:category term="CONVT_NO_NUMBER" label="ABAP runtime error"/>
<atom:id>/sap/bc/adt/vit/runtime/dumps/20260619080000host_NWF_00</atom:id>
<atom:summary type="html">&lt;p&gt;not a number&lt;/p&gt;</atom:summary>
<atom:title>CONVT_NO_NUMBER</atom:title>
<atom:published>2026-06-19T08:00:00Z</atom:published>
</atom:entry>
</atom:feed>""").encode()


def test_parse_dumps_feed():
    dumps = parse_dumps_feed(DUMPS_FEED)
    assert len(dumps) == 2
    d = dumps[0]
    assert d["uri"] == _DUMP_ID
    assert d["title"] == "The exception CX_SY_ZERODIVIDE was raised."
    assert d["author"] == "CB99"
    assert d["date"] == "2026-06-20T11:12:13Z"
    assert ("UNCAUGHT_EXCEPTION", "ABAP runtime error") in d["categories"]
    assert "Error analysis" in d["summary"]      # full dump embedded in feed


def test_parse_dumps_feed_empty():
    assert parse_dumps_feed(b"") == []
    assert parse_dumps_feed(b"<not xml") == []


def test_list_dumps_newest_first_and_error_term():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["accept"] = req.headers.get("accept", "")
        return httpx.Response(200, content=DUMPS_FEED,
                              headers={"content-type": "application/atom+xml"})

    out = _client(handler).list_dumps(_sys())
    assert "type=feed" in seen["accept"]
    assert "/sap/bc/adt/runtime/dumps" in seen["url"]
    assert out.index("20260620111213") < out.index("20260619080000")
    # error term comes from the 'ABAP runtime error' category, not the program
    assert "[UNCAUGHT_EXCEPTION]" in out and "CB99" in out


def test_list_dumps_date_filter_passed():
    seen = {}
    _client(lambda r: seen.update(url=str(r.url)) or httpx.Response(
        200, content=DUMPS_FEED)).list_dumps(
        _sys(), from_date="20260601000000", to_date="20260625000000")
    assert "from=20260601000000" in seen["url"]
    assert "to=20260625000000" in seen["url"]


def test_list_dumps_empty():
    out = _client(lambda r: httpx.Response(
        200, content=b'<atom:feed xmlns:atom="http://www.w3.org/2005/Atom"/>'
        )).list_dumps(_sys())
    assert "No runtime dumps" in out


def test_get_dump_resolves_summary_from_feed():
    # get_dump matches the entry by id and flattens its summary — no second
    # fetch of the (adt://, non-HTTP) detail link.
    def handler(req):
        assert "type=feed" in req.headers.get("accept", "")  # hits the feed
        return httpx.Response(200, content=DUMPS_FEED,
                              headers={"content-type": "application/atom+xml"})

    out = _client(handler).get_dump(_sys(), _DUMP_ID)
    assert "Error analysis" in out
    assert "CX_SY_ZERODIVIDE" in out
    assert "Division by zero" in out          # &nbsp; normalised
    assert "POST\t42" in out                  # table cells kept apart
    assert "<" not in out                     # tags stripped


def test_get_dump_accepts_uri_with_fragment():
    out = _client(lambda r: httpx.Response(200, content=DUMPS_FEED)).get_dump(
        _sys(), _DUMP_ID + "#/source/main")
    assert "CX_SY_ZERODIVIDE" in out          # fragment stripped before match


def test_get_dump_requires_uri():
    assert "required" in _client(
        lambda r: httpx.Response(200)).get_dump(_sys(), "")


def test_get_dump_not_found_in_feed():
    out = _client(lambda r: httpx.Response(200, content=DUMPS_FEED)).get_dump(
        _sys(), "/sap/bc/adt/vit/runtime/dumps/99999999999999nope")
    assert "not found in feed" in out


def test_html_to_text_basics():
    out = html_to_text(
        "<style>x{}</style><h1>T</h1><p>a&nbsp;b</p>"
        "<table><tr><td>x</td><td>y</td></tr></table>")
    assert "T" in out and "a b" in out and "x\ty" in out
    assert "<" not in out
