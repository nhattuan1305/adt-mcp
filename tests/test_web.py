import httpx
from starlette.testclient import TestClient
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient
from adt_mcp.server import build_server


def _app(tmp_path, handler=None):
    reg = SystemRegistry(str(tmp_path / "s.json"))
    if handler is None:
        handler = lambda req: httpx.Response(200, text="")
    adt = ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))
    mcp = build_server(reg, adt)
    return TestClient(mcp.streamable_http_app()), reg


def test_post_then_list(tmp_path):
    client, reg = _app(tmp_path)
    r = client.post("/api/systems", json={
        "name": "dev", "url": "https://h", "client": "080",
        "language": "JA", "auth": "basic",
        "username": "u", "password": "p"})
    assert r.json() == {"ok": True}
    r2 = client.get("/api/systems")
    names = [s["name"] for s in r2.json()["systems"]]
    assert "dev" in names
    # Secret not exposed in list.
    assert "password" not in r2.json()["systems"][0]


def test_delete(tmp_path):
    client, reg = _app(tmp_path)
    client.post("/api/systems", json={
        "name": "dev", "url": "https://h", "client": "080",
        "language": "JA", "auth": "basic"})
    r = client.delete("/api/systems/dev")
    assert r.json() == {"ok": True}
    assert client.get("/api/systems").json()["systems"] == []


def test_test_connection(tmp_path):
    def handler(req):
        return httpx.Response(200, text="ok")
    client, reg = _app(tmp_path, handler)
    client.post("/api/systems", json={
        "name": "dev", "url": "https://h", "client": "080",
        "language": "JA", "auth": "basic", "username": "u", "password": "p"})
    r = client.post("/api/systems/dev/test")
    assert r.json()["result"] == "OK"


def test_index_served(tmp_path):
    client, reg = _app(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "ADT MCP" in r.text


def test_login_requires_name_and_url(tmp_path):
    client, reg = _app(tmp_path)
    r = client.post("/api/systems/login", json={"name": "", "url": ""})
    assert "required" in r.json()["result"].lower()


def test_login_headless_requires_credentials(tmp_path):
    client, reg = _app(tmp_path)
    r = client.post("/api/systems/login", json={
        "name": "x", "url": "https://h", "mode": "headless"})
    assert "username and password" in r.json()["result"].lower()


def test_refresh_unknown_system(tmp_path):
    client, reg = _app(tmp_path)
    r = client.post("/api/systems/nope/refresh")
    assert "unknown system" in r.json()["result"].lower()
