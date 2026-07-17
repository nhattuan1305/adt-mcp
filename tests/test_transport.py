import httpx
from adt_mcp.registry import System
from adt_mcp.adt_client import ADTClient, parse_transports


def _sys(**kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="EN", auth="basic", username="DEVUSER", password="p",
                cookie_file=None, cookie_string=None, allow_write=True,
                write_packages=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


_TREE = b'''<?xml version="1.0" encoding="utf-8"?>
<tm:root xmlns:tm="http://www.sap.com/cts/adt/tm"
         xmlns:adtcore="http://www.sap.com/adt/core">
  <tm:workbench tm:category="workbench">
    <tm:modifiable>
      <tm:request tm:number="CB9K900123" tm:parent="" tm:desc="My RAP change"
                  tm:type="K" tm:status="D" tm:target="LOCAL"
                  adtcore:createdBy="DEVUSER">
        <tm:task tm:number="CB9K900124" tm:desc="task" tm:type="Q"
                 tm:status="D" tm:owner="DEVUSER"/>
      </tm:request>
    </tm:modifiable>
  </tm:workbench>
</tm:root>'''


def test_parse_transports_reads_requests():
    rows = parse_transports(_TREE)
    assert len(rows) == 1
    r = rows[0]
    assert r["number"] == "CB9K900123"
    assert r["description"] == "My RAP change"
    assert r["type"] == "K"
    assert r["status"] == "D"
    assert r["owner"] == "DEVUSER"


def test_parse_transports_empty_root():
    empty = (b'<?xml version="1.0"?><tm:root '
             b'xmlns:tm="http://www.sap.com/cts/adt/tm"/>')
    assert parse_transports(empty) == []
    assert parse_transports(b"") == []


def test_list_transports_formats_rows():
    def handler(req):
        if "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        return httpx.Response(200, content=_TREE,
                              headers={"content-type": "application/xml"})
    out = _client(handler).list_transports(_sys())
    assert "CB9K900123" in out
    assert "My RAP change" in out


def test_list_transports_none_open():
    empty = (b'<tm:root xmlns:tm="http://www.sap.com/cts/adt/tm"/>')
    def handler(req):
        if "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        return httpx.Response(200, content=empty,
                              headers={"content-type": "application/xml"})
    out = _client(handler).list_transports(_sys())
    assert "No open transport" in out


def test_create_transport_posts_body_and_returns_number():
    seen = {"url": None, "body": None}

    def handler(req):
        if req.method == "GET" and "discovery" in str(req.url):
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        seen["url"] = str(req.url)
        seen["body"] = req.content.decode("utf-8")
        # ADT echoes the created request with its new number
        return httpx.Response(
            200, headers={"content-type": "application/xml"},
            content=b'<?xml version="1.0"?><tm:root '
                    b'xmlns:tm="http://www.sap.com/cts/adt/tm" '
                    b'xmlns:adtcore="http://www.sap.com/adt/core">'
                    b'<tm:request tm:number="CB9K900130" tm:desc="New feature" '
                    b'tm:type="K" tm:status="D"/></tm:root>')

    out = _client(handler).create_transport(_sys(), "New feature")
    assert "CB9K900130" in out
    assert out.startswith("OK")
    assert "/cts/transportrequests" in seen["url"]
    assert "New feature" in seen["body"]


def test_create_transport_requires_allow_write():
    out = _client(lambda r: httpx.Response(500)).create_transport(
        _sys(allow_write=False), "x")
    assert "disabled" in out.lower()
