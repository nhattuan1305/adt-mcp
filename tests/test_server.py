import asyncio
from unittest.mock import patch

import httpx
from adt_mcp.registry import System, SystemRegistry
from adt_mcp.adt_client import ADTClient
from adt_mcp.server import format_systems, resolve_and_get, build_server


def _reg(tmp_path):
    reg = SystemRegistry(str(tmp_path / "s.json"))
    reg.upsert(System(name="hax", url="https://h", client="080",
                      language="JA", auth="cookie", username=None,
                      password=None, cookie_file=None,
                      cookie_string="SAP_SESSIONID=z"))
    return reg


def test_format_systems(tmp_path):
    out = format_systems(_reg(tmp_path).list())
    assert "hax" in out
    assert "https://h" in out


def test_resolve_and_get_unknown_system(tmp_path):
    reg = _reg(tmp_path)
    adt = ADTClient(httpx.Client())
    out = resolve_and_get(reg, adt, "nope", "CLAS", "ZCL_X", None)
    assert "unknown system" in out.lower()


def test_resolve_and_get_ok(tmp_path):
    reg = _reg(tmp_path)

    def handler(req):
        return httpx.Response(200, text="CLASS zcl_x.")

    adt = ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))
    out = resolve_and_get(reg, adt, "hax", "CLAS", "ZCL_X", None)
    assert out == "CLASS zcl_x."


def test_refresh_cookies_for_offloads_playwright_off_event_loop(tmp_path):
    """The refresh_cookies_for MCP tool must run sync Playwright in a worker
    thread, not the asyncio event loop thread (sync_playwright() raises if a
    loop is running in the current thread). Mirrors the web-admin routes."""
    reg = SystemRegistry(str(tmp_path / "s.json"))
    reg.upsert(System(name="dev", url="https://h", client="080",
                      language="EN", auth="cookie", username="u",
                      password="p", cookie_file=str(tmp_path / "c.txt"),
                      cookie_string=None))
    adt = ADTClient(httpx.Client())
    mcp = build_server(reg, adt)

    observed = {}

    def fake_refresh(url, username, password, cookie_file):
        try:
            asyncio.get_running_loop()
            observed["loop_running"] = True
        except RuntimeError:
            observed["loop_running"] = False
        return "OK: captured 1 session cookies"

    with patch("adt_mcp.server.refresh_cookies", fake_refresh):
        asyncio.run(mcp.call_tool("refresh_cookies_for", {"system": "dev"}))

    assert observed.get("loop_running") is False, (
        "refresh_cookies ran inside the event loop thread — sync Playwright "
        "would crash; it must be offloaded to a worker thread")
