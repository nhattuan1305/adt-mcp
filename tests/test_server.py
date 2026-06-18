import httpx
from adt_mcp.registry import System, SystemRegistry
from adt_mcp.adt_client import ADTClient
from adt_mcp.server import format_systems, resolve_and_get


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
