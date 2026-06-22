"""Find the correct DOMA (domain) create body. Run on VM: python diag_doma.py"""
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
ALV = 'adtcore:abapLanguageVersion="cloudDevelopment"'


def body(root, ns, name, extra=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:description="diag" adtcore:name="{name}" '
            f'adtcore:type="DOMA/DD" adtcore:language="EN" '
            f'adtcore:masterLanguage="EN" {ALV} '
            f'adtcore:responsible="{RESP}" {extra}>\n'
            f'  <adtcore:packageRef adtcore:name="{PKG}"/>\n</{root}>')


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)

    # First: dump an EXISTING domain's metadata (ground truth root/namespace)
    objs = adt.search_objects(s, "Z*", 100)
    duri = None
    if isinstance(objs, list):
        for o in objs:
            if "/ddic/domains/" in o.get("uri", ""):
                duri = o["uri"]; break
    print("existing domain uri:", duri)
    if duri:
        r = adt._get(s, f"{base_url(s.url)}{duri}?sap-client={s.client}",
                     "application/*")
        if r.status_code == 200:
            t = r.text
            print("ROOT TAG:", t[:t.find(">") + 1])

    variants = [
        ("domain:domain  dictionary/domain", "domain:domain",
         'xmlns:domain="http://www.sap.com/dictionary/domain"'),
        ("doma:domain    adt/ddic/domains", "doma:domain",
         'xmlns:doma="http://www.sap.com/adt/ddic/domains"'),
        ("blue:wbobj     wbobj/dictionary/doma", "blue:wbobj",
         'xmlns:blue="http://www.sap.com/wbobj/dictionary/doma"'),
    ]
    print("\n--- DOMA create probes ---")
    for label, root, ns in variants:
        url = f"{base_url(s.url)}/sap/bc/adt/ddic/domains"
        if TR:
            url += f"?corrNr={quote(TR, safe='')}"
        b = body(root, ns, f"ZZDOM{SFX}{variants.index((label,root,ns))}")
        r = adt._post(s, url, "application/*", b.encode("utf-8"), "application/*")
        ok = r.status_code in (200, 201)
        print(f"{label:36s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:300])


if __name__ == "__main__":
    main()
