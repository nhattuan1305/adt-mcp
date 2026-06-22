"""Match vibing-steampunk's approach: minimal body + per-type Content-Type/Accept.
Run on VM:  cd C:\\adt-mcp ; git pull ; python diag_create4.py
Prints FULL response so we see exactly which combo the live system accepts.
"""
import os
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient, base_url

SYS = os.environ.get("DIAG_SYS", "VNEXT")
RESP = "CB0000000000"


def minimal(root, ns, name, adt_type, *, extra=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:description="diag" adtcore:name="{name}" '
            f'adtcore:type="{adt_type}" adtcore:responsible="{RESP}" {extra}>\n'
            f'  <adtcore:packageRef adtcore:name="$TMP"/>\n</{root}>')


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)  # pre-warm CSRF so first POST isn't a spurious 403
    print(f"system={s.name} language={s.language!r}\n")

    def post(label, path, body, ct, accept):
        r = adt._post(s, f"{base_url(s.url)}{path}", accept,
                      body.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        print(f"{label:50s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:280])

    TBL_CT = "application/vnd.sap.adt.tables.v2+xml"
    DDL_CT = "application/vnd.sap.adt.ddic.ddlsources.v2+xml"
    CLS_CT = "application/vnd.sap.adt.oo.classes.v4+xml"

    bt = minimal("blue:blueSource",
                 'xmlns:blue="http://www.sap.com/wbobj/blue"',
                 "ZZV4TABLA", "TABL/DT")
    post("TABL  tables.v2 (vibing)", "/sap/bc/adt/ddic/tables", bt, TBL_CT, TBL_CT)
    post("TABL  application/* (current)", "/sap/bc/adt/ddic/tables",
         minimal("blue:blueSource", 'xmlns:blue="http://www.sap.com/wbobj/blue"',
                 "ZZV4TABLB", "TABL/DT"), "application/*", "application/*")

    bd = minimal("ddl:ddlSource",
                 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
                 "ZZV4DDLSA", "DDLS/DF")
    post("DDLS  application/* (vibing)", "/sap/bc/adt/ddic/ddl/sources", bd,
         "application/*", "application/*")
    post("DDLS  ddlsources.v2", "/sap/bc/adt/ddic/ddl/sources",
         minimal("ddl:ddlSource",
                 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
                 "ZZV4DDLSB", "DDLS/DF"), DDL_CT, DDL_CT)

    bc = minimal("class:abapClass",
                 'xmlns:class="http://www.sap.com/adt/oo/classes"',
                 "ZZV4CLASA", "CLAS/OC")
    post("CLAS  application/* (vibing)", "/sap/bc/adt/oo/classes", bc,
         "application/*", "application/*")
    post("CLAS  classes.v4", "/sap/bc/adt/oo/classes",
         minimal("class:abapClass",
                 'xmlns:class="http://www.sap.com/adt/oo/classes"',
                 "ZZV4CLASB", "CLAS/OC"), CLS_CT, CLS_CT)


if __name__ == "__main__":
    main()
