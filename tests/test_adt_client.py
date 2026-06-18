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
