import httpx
import pytest
from adt_mcp.registry import System
from adt_mcp.adt_client import (
    ADTClient, check_write, object_root_path, parse_lock_handle,
    parse_activation, build_creation_body)


def _sys(allow_write=True, **kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="JA", auth="basic", username="u", password="p",
                cookie_file=None, cookie_string=None,
                allow_write=allow_write, write_packages=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


# --- safety ---
def test_check_write_disabled():
    assert "disabled" in check_write(_sys(allow_write=False), "ZPKG").lower()


def test_check_write_package_whitelist():
    assert check_write(_sys(), "ZPKG") is None          # Z* default
    assert check_write(_sys(), "$TMP") is None
    assert "not in write_packages" in check_write(_sys(), "SAPMV45A")
    assert check_write(_sys(write_packages=["ZRAP_*"]), "ZRAP_X") is None
    assert check_write(_sys(write_packages=["ZRAP_*"]), "ZOTHER")


# --- parsers / paths ---
def test_object_root_path():
    assert object_root_path("CLAS", "zcl_a") == "/sap/bc/adt/oo/classes/ZCL_A"
    assert object_root_path("DDLS", "zr") == "/sap/bc/adt/ddic/ddl/sources/ZR"
    assert object_root_path("FUGR", "zfm", "zfg").endswith("/groups/ZFG/fmodules/ZFM")


def test_parse_lock_handle():
    xml = b'<asx><values><DATA><LOCK_HANDLE>ABC123</LOCK_HANDLE></DATA></values></asx>'
    assert parse_lock_handle(xml) == "ABC123"
    assert parse_lock_handle(b"") == ""


def test_parse_activation():
    ok = b'<chkl:messages xmlns:chkl="x"/>'
    assert parse_activation(ok) == "OK"
    err = (b'<chkl:messages xmlns:chkl="x"><msg severity="E" '
           b'shortText="syntax error"/></chkl:messages>')
    assert "activation failed" in parse_activation(err)
    assert "syntax error" in parse_activation(err)


def test_build_creation_body_srvd_and_srvb():
    srvd = build_creation_body("SRVD", "zsd", "ZP", "d", "U")
    assert 'srvd:srvdSourceType="S"' in srvd and 'adtcore:name="ZSD"' in srvd
    srvb = build_creation_body("SRVB", "zsb", "ZP", "d", "U",
                               service_definition="zsd", binding_version="V4")
    assert 'srvb:serviceDefinition adtcore:name="ZSD"' in srvb
    assert 'srvb:version="V4"' in srvb


# --- edit sequence ---
def _seq_handler(calls, lock_body=None, put_status=200):
    lock_body = lock_body or (
        b'<a><DATA><LOCK_HANDLE>LH1</LOCK_HANDLE></DATA></a>')

    def handler(req):
        u = str(req.url)
        calls.append((req.method, u))
        if req.method == "GET" and "discovery" in u:        # csrf fetch
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if req.method == "GET":                              # object_package
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<root><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZPKG"/></root>')
        if "_action=LOCK" in u:
            return httpx.Response(200, content=lock_body,
                                  headers={"content-type": "application/xml"})
        if req.method == "PUT":
            return httpx.Response(put_status, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b'<messages/>')
        return httpx.Response(404, text="nf")
    return handler


def test_update_source_ok():
    calls = []
    out = _client(_seq_handler(calls)).update_source(
        _sys(), "CLAS", "ZCL_A", "CLASS zcl_a.")
    assert out == "OK"
    methods = [m for m, _ in calls]
    assert "PUT" in methods
    assert any("_action=LOCK" in u for _, u in calls)
    assert any("_action=UNLOCK" in u for _, u in calls)
    assert any("activation" in u for _, u in calls)


def test_update_source_gate_blocks_before_http():
    calls = []
    out = _client(_seq_handler(calls)).update_source(
        _sys(allow_write=False), "CLAS", "ZCL_A", "x")
    assert "disabled" in out.lower()
    assert calls == []


def test_update_source_nomodification_does_not_block():
    # NoModification is informational on cloud; a handle is present so the
    # write must proceed (PUT happens) and succeed.
    nm = (b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE>'
          b'<MODIFICATION_SUPPORT>NoModification</MODIFICATION_SUPPORT></DATA></a>')
    calls = []
    out = _client(_seq_handler(calls, lock_body=nm)).update_source(
        _sys(), "CLAS", "ZCL_A", "x")
    assert out == "OK"
    assert "PUT" in [m for m, _ in calls]


def test_update_source_lock_no_handle_fails():
    nm = b'<a><DATA><CORRNR/></DATA></a>'  # no LOCK_HANDLE
    out = _client(_seq_handler([], lock_body=nm)).update_source(
        _sys(), "CLAS", "ZCL_A", "x")
    assert "no lock handle" in out.lower()


def test_create_object_srvb_requires_servicedef():
    out = _client(lambda r: httpx.Response(200)).create_object(
        _sys(), "SRVB", "ZSB", "ZPKG", service_definition=None)
    assert "service_definition" in out


def test_create_object_ok_no_source():
    def handler(req):
        if "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        return httpx.Response(201, text="")
    out = _client(handler).create_object(_sys(), "DDLS", "ZR", "ZPKG", "desc")
    assert out.startswith("OK: created DDLS ZR")


# --- CSRF token caching + refetch (fix 1) ---
def test_csrf_token_cached_across_posts():
    gets = {"n": 0}

    def handler(req):
        if req.method == "GET" and "discovery" in str(req.url):
            gets["n"] += 1
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        return httpx.Response(200, content=b"<messages/>")

    c = _client(handler)
    c.activate(_sys(), "CLAS", "ZCL_A")
    c.activate(_sys(), "CLAS", "ZCL_B")
    assert gets["n"] == 1  # token fetched once, reused for the 2nd activate


def test_post_refetches_csrf_on_403_required():
    state = {"tokens": ["T1", "T2"], "i": 0, "posts": []}

    def handler(req):
        u = str(req.url)
        if req.method == "GET" and "discovery" in u:
            t = state["tokens"][min(state["i"], len(state["tokens"]) - 1)]
            state["i"] += 1
            return httpx.Response(200, headers={"x-csrf-token": t})
        if req.method == "POST" and "activation" in u:
            state["posts"].append(req.headers.get("x-csrf-token"))
            if req.headers.get("x-csrf-token") == "T1":
                return httpx.Response(403, headers={"x-csrf-token": "Required"},
                                      text="CSRF token validation failed")
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404)

    out = _client(handler).activate(_sys(), "CLAS", "ZCL_A")
    assert out == "OK"
    assert state["posts"] == ["T1", "T2"]  # rejected → refetched & retried


# --- write respects session-cookie rotation (fix 2) ---
def test_write_uses_jar_and_respects_cookie_rotation():
    seen = {}

    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if req.method == "GET":  # object_package
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZPKG"/></r>')
        if "_action=LOCK" in u:
            # server rotates the session cookie on lock
            return httpx.Response(
                200, content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>',
                headers={"content-type": "application/xml",
                         "set-cookie": "SAP_SESSIONID=ROTATED; Path=/"})
        if req.method == "PUT":
            seen["put_cookie"] = req.headers.get("cookie")
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404)

    s = _sys(auth="cookie", username=None, password=None,
             cookie_string="SAP_SESSIONID=ORIG")
    out = _client(handler).update_source(s, "CLAS", "ZCL_A", "x")
    assert out == "OK"
    assert "ROTATED" in seen["put_cookie"]   # PUT carries the rotated session
    assert "ORIG" not in seen["put_cookie"]  # not the stale original


# --- stuck-lock / session-expired surfaced (fix 3) ---
def test_update_source_stuck_lock_surfaced():
    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if req.method == "GET":
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZPKG"/></r>')
        if "_action=LOCK" in u:
            return httpx.Response(
                200, content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>',
                headers={"content-type": "application/xml"})
        if req.method == "PUT":
            return httpx.Response(403, text="session expired")
        if "_action=UNLOCK" in u:
            return httpx.Response(403, text="session expired")  # unlock fails too
        return httpx.Response(404)

    out = _client(handler).update_source(_sys(), "CLAS", "ZCL_A", "x")
    assert "may remain locked" in out.lower()
    assert "refresh" in out.lower()


def test_update_source_put_fail_but_unlock_ok_no_stuck_message():
    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if req.method == "GET":
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZPKG"/></r>')
        if "_action=LOCK" in u:
            return httpx.Response(
                200, content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>',
                headers={"content-type": "application/xml"})
        if req.method == "PUT":
            return httpx.Response(400, text="syntax error in source")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")  # unlock succeeds → not stuck
        return httpx.Response(404)

    out = _client(handler).update_source(_sys(), "CLAS", "ZCL_A", "x")
    assert "may remain locked" not in out.lower()
    assert "syntax error" in out.lower()
