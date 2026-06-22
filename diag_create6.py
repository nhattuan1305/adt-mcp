"""Verify CLAS/INTF/DDLS create in a REAL cloud package (default ZRAP_IF_VI901).
Run on VM:  cd C:\\adt-mcp ; git pull ; python diag_create6.py
Optional:   set DIAG_PKG=... ; set DIAG_TR=<transport>   (if pkg is transportable)
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
ALV = 'adtcore:abapLanguageVersion="cloudDevelopment"'


def body(root, ns, name, adt_type, *, extra=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:description="diag" adtcore:name="{name}" '
            f'adtcore:type="{adt_type}" adtcore:language="EN" '
            f'adtcore:masterLanguage="EN" {ALV} '
            f'adtcore:responsible="{RESP}" {extra}>\n'
            f'  <adtcore:packageRef adtcore:name="{PKG}"/>\n</{root}>')


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)
    print(f"system={s.name} pkg={PKG} transport={TR or '(none)'} suffix={SFX}\n")

    def post(label, path, b, ct):
        url = f"{base_url(s.url)}{path}"
        if TR:
            url += f"?corrNr={quote(TR, safe='')}"
        r = adt._post(s, url, ct, b.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        print(f"{label:32s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:300])

    post("CLAS", "/sap/bc/adt/oo/classes",
         body("class:abapClass", 'xmlns:class="http://www.sap.com/adt/oo/classes"',
              f"ZCLVI901{SFX}", "CLAS/OC"), "application/*")
    post("INTF", "/sap/bc/adt/oo/interfaces",
         body("intf:abapInterface", 'xmlns:intf="http://www.sap.com/adt/oo/interfaces"',
              f"ZIFVI901{SFX}", "INTF/OI"), "application/*")
    post("DDLS", "/sap/bc/adt/ddic/ddl/sources",
         body("ddl:ddlSource", 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
              f"ZDLVI901{SFX}", "DDLS/DF"), "application/*")


if __name__ == "__main__":
    main()
