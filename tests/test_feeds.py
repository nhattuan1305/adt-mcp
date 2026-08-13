import httpx
from adt_mcp.registry import System
from adt_mcp.adt_client import (
    ADTClient, parse_feed_catalog, parse_feed_entries, FEED_ALIASES)


def _sys(**kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="EN", auth="basic", username="DEVUSER", password="p",
                cookie_file=None, cookie_string=None, allow_write=False,
                write_packages=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


_CATALOG = b'''<?xml version="1.0" encoding="utf-8"?>
<atom:feed xmlns:atom="http://www.w3.org/2005/Atom">
  <atom:title>ABAP System Monitoring</atom:title>
  <atom:entry>
    <atom:content type="application/atom+xml" src="/sap/bc/adt/gw/errorlog"/>
    <atom:id>/sap/bc/adt/gw/errorlog</atom:id>
    <atom:link href="/sap/bc/adt/gw/errorlog" rel="alternate"/>
    <atom:summary>SAP Gateway Error Log</atom:summary>
    <atom:title>SAP Gateway Error Log</atom:title>
  </atom:entry>
  <atom:entry>
    <atom:id>/sap/bc/adt/runtime/systemmessages</atom:id>
    <atom:link href="/sap/bc/adt/runtime/systemmessages" rel="alternate"/>
    <atom:summary>ABAP System Messages</atom:summary>
    <atom:title>ABAP System Messages</atom:title>
  </atom:entry>
</atom:feed>'''

_GW_FEED = b'''<?xml version="1.0" encoding="utf-8"?>
<atom:feed xmlns:atom="http://www.w3.org/2005/Atom">
  <atom:entry>
    <atom:author><atom:name>DEVUSER</atom:name></atom:author>
    <atom:id>FrontendError/AAA</atom:id>
    <atom:summary type="html">&lt;h4&gt;HTTP link&lt;/h4&gt; no authorization</atom:summary>
    <atom:title>Frontend Error: No authorization</atom:title>
    <atom:updated>2026-07-17T02:55:51Z</atom:updated>
  </atom:entry>
  <atom:entry>
    <atom:author><atom:name>OTHERUSER</atom:name></atom:author>
    <atom:id>FrontendError/BBB</atom:id>
    <atom:title>Another gateway error</atom:title>
    <atom:updated>2026-07-16T01:00:00Z</atom:updated>
  </atom:entry>
</atom:feed>'''


def test_feed_aliases_cover_key_feeds():
    assert FEED_ALIASES["gateway_log"] == "SAP Gateway Error Log"
    assert FEED_ALIASES["system_messages"] == "ABAP System Messages"
    assert FEED_ALIASES["dumps"] == "ABAP Runtime Errors"


def test_parse_feed_catalog():
    feeds = parse_feed_catalog(_CATALOG)
    assert len(feeds) == 2
    assert feeds[0]["title"] == "SAP Gateway Error Log"
    assert feeds[0]["href"] == "/sap/bc/adt/gw/errorlog"
    assert feeds[1]["title"] == "ABAP System Messages"


def test_parse_feed_entries():
    ents = parse_feed_entries(_GW_FEED)
    assert len(ents) == 2
    assert ents[0]["title"] == "Frontend Error: No authorization"
    assert ents[0]["author"] == "DEVUSER"
    assert ents[0]["date"] == "2026-07-17T02:55:51Z"
    assert "no authorization" in ents[0]["summary"].lower()


def _catalog_handler(feed_body):
    def handler(req):
        u = str(req.url)
        if "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if u.split("?")[0].endswith("/sap/bc/adt/feeds"):
            return httpx.Response(200, content=_CATALOG,
                                  headers={"content-type": "application/atom+xml"})
        if "/gw/errorlog" in u:
            return httpx.Response(200, content=feed_body,
                                  headers={"content-type": "application/atom+xml"})
        return httpx.Response(404)
    return handler


def test_list_feeds_shows_titles_and_aliases():
    out = _client(_catalog_handler(_GW_FEED)).list_feeds(_sys())
    assert "SAP Gateway Error Log" in out
    assert "gateway_log" in out          # friendly alias surfaced


def test_read_feed_resolves_alias_and_formats():
    out = _client(_catalog_handler(_GW_FEED)).read_feed(_sys(), "gateway_log")
    assert "Frontend Error: No authorization" in out
    assert "Another gateway error" in out


def test_read_feed_resolves_by_title_substring():
    out = _client(_catalog_handler(_GW_FEED)).read_feed(_sys(), "Gateway")
    assert "Frontend Error" in out


def test_read_feed_respects_max():
    out = _client(_catalog_handler(_GW_FEED)).read_feed(_sys(), "gateway_log", max=1)
    assert "Frontend Error: No authorization" in out
    assert "Another gateway error" not in out


def test_read_feed_filters_by_user():
    out = _client(_catalog_handler(_GW_FEED)).read_feed(
        _sys(), "gateway_log", user="OTHERUSER")
    assert "Another gateway error" in out
    assert "Frontend Error: No authorization" not in out


def test_read_feed_unknown_feed_lists_options():
    out = _client(_catalog_handler(_GW_FEED)).read_feed(_sys(), "nonsense")
    assert out.startswith("Error")
    assert "gateway_log" in out or "SAP Gateway Error Log" in out
