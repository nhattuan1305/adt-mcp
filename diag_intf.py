"""Why does INTF read a blank abapLanguageVersion? Dump canonical interface
metadata and probe create variants. Run on VM: python diag_intf.py
"""
import os
import time
import httpx
from urllib.parse import quote
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient, base_url

SYS = os.environ.get("DIAG_SYS", "VNEXT")
PKG = os.environ.get("DIAG_PKG", "ZRAP_IF_VI901")
TR = os.environ.get("DIAG_TR", "")
RESP = "CB0000000000"
SFX = str(int(time.time()) % 1000)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)

    # 1) find an existing interface and dump its metadata XML
    objs = adt.search_objects(s, "Z*", 80)
    uri = None
    if isinstance(objs, list):
        for o in objs:
            if "/oo/interfaces/" in o.get("uri", ""):
                uri = o["uri"]; break
    print("existing interface uri:", uri)
    if uri:
        root_url = f"{base_url(s.url)}{uri}?sap-client={s.client}"
        for acc in ("application/vnd.sap.adt.oo.interfaces.v5+xml",
                    "application/vnd.sap.adt.oo.interfaces.v2+xml",
                    "application/*"):
            r = adt._get(s, root_url, acc)
            if r.status_code == 200:
                print(f"\n--- INTF metadata (Accept={acc}) ---")
                # print just the root open tag (attributes)
                t = r.text
                print(t[:t.find(">") + 1] if ">" in t else t[:1500])
                break
            print(f"  {acc} -> HTTP {r.status_code}")

    # 2) probe INTF create variants in PKG
    def intf_body(name, attrs_order):
        ns = ('xmlns:intf="http://www.sap.com/adt/oo/interfaces" '
              'xmlns:adtcore="http://www.sap.com/adt/core"')
        amap = {
            "desc": 'adtcore:description="diag"',
            "name": f'adtcore:name="{name}"',
            "type": 'adtcore:type="INTF/OI"',
            "lang": 'adtcore:language="EN"',
            "mlang": 'adtcore:masterLanguage="EN"',
            "alv": 'adtcore:abapLanguageVersion="cloudDevelopment"',
            "resp": f'adtcore:responsible="{RESP}"',
        }
        attrs = " ".join(amap[k] for k in attrs_order)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<intf:abapInterface {ns} {attrs}>\n'
                f'  <adtcore:packageRef adtcore:name="{PKG}"/>\n'
                '</intf:abapInterface>')

    def post(label, body):
        url = f"{base_url(s.url)}/sap/bc/adt/oo/interfaces"
        if TR:
            url += f"?corrNr={quote(TR, safe='')}"
        r = adt._post(s, url, "application/*", body.encode("utf-8"), "application/*")
        ok = r.status_code in (200, 201)
        print(f"{label:34s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:240])

    print("\n--- INTF create probes ---")
    post("A current order",
         intf_body(f"ZIFA{SFX}", ["desc", "name", "type", "lang", "mlang", "alv", "resp"]))
    post("B alv right after type",
         intf_body(f"ZIFB{SFX}", ["desc", "name", "type", "alv", "lang", "mlang", "resp"]))
    post("C alv first",
         intf_body(f"ZIFC{SFX}", ["alv", "desc", "name", "type", "lang", "mlang", "resp"]))


if __name__ == "__main__":
    main()
