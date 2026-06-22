"""Convergence run: winning recipe (lang+masterLang+abapLanguageVersion) per type.
Run on VM:  cd C:\\adt-mcp ; git pull ; python diag_create5.py
"""
import os
import time
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient, base_url

SYS = os.environ.get("DIAG_SYS", "VNEXT")
RESP = "CB0000000000"
SFX = str(int(time.time()) % 1000)  # unique-ish suffix to avoid name clashes
ALV = 'adtcore:abapLanguageVersion="cloudDevelopment"'


def body(root, ns, name, adt_type, *, extra=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:description="diag" adtcore:name="{name}" '
            f'adtcore:type="{adt_type}" adtcore:language="EN" '
            f'adtcore:masterLanguage="EN" {ALV} '
            f'adtcore:responsible="{RESP}" {extra}>\n'
            f'  <adtcore:packageRef adtcore:name="$TMP"/>\n</{root}>')


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)
    print(f"system={s.name} language={s.language!r} suffix={SFX}\n")

    def post(label, path, b, ct):
        r = adt._post(s, f"{base_url(s.url)}{path}", ct, b.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        print(f"{label:42s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:300])

    NS = {
        "CLAS": ("class:abapClass", 'xmlns:class="http://www.sap.com/adt/oo/classes"',
                 "/sap/bc/adt/oo/classes", "CLAS/OC"),
        "INTF": ("intf:abapInterface", 'xmlns:intf="http://www.sap.com/adt/oo/interfaces"',
                 "/sap/bc/adt/oo/interfaces", "INTF/OI"),
        "DDLS": ("ddl:ddlSource", 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
                 "/sap/bc/adt/ddic/ddl/sources", "DDLS/DF"),
        "DDLX": ("ddlx:ddlxSource", 'xmlns:ddlx="http://www.sap.com/adt/ddic/ddlxsources"',
                 "/sap/bc/adt/ddic/ddlx/sources", "DDLX/EX"),
    }
    for k, (root, ns, path, at) in NS.items():
        post(f"{k}  application/*", path,
             body(root, ns, f"ZZ{k}{SFX}", at), "application/*")

    # SRVD needs srvdSourceType
    post("SRVD  application/*", "/sap/bc/adt/ddic/srvd/sources",
         body("srvd:srvdSource",
              'xmlns:srvd="http://www.sap.com/adt/ddic/srvdsources"',
              f"ZZSRVD{SFX}", "SRVD/SRV", extra='srvd:srvdSourceType="S"'),
         "application/*")

    # TABL: two content types
    tb = body("blue:blueSource", 'xmlns:blue="http://www.sap.com/wbobj/blue"',
              f"ZZTABLA{SFX}", "TABL/DT")
    post("TABL  application/*", "/sap/bc/adt/ddic/tables", tb, "application/*")
    post("TABL  tables.v2", "/sap/bc/adt/ddic/tables",
         body("blue:blueSource", 'xmlns:blue="http://www.sap.com/wbobj/blue"',
              f"ZZTABLB{SFX}", "TABL/DT"),
         "application/vnd.sap.adt.tables.v2+xml")


if __name__ == "__main__":
    main()
