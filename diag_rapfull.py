"""Probe create of the full RAP object set in a real cloud package.
Run on VM:  cd C:\\adt-mcp ; git pull ; python diag_rapfull.py
Optional:   set DIAG_PKG=... ; set DIAG_TR=<transport>
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

# label: (path, root, namespace, adt_type, content_type, extra_attrs)
TYPES = [
    ("TABL", "/sap/bc/adt/ddic/tables", "blue:blueSource",
     'xmlns:blue="http://www.sap.com/wbobj/blue"', "TABL/DT", "application/*", ""),
    ("DDLS", "/sap/bc/adt/ddic/ddl/sources", "ddl:ddlSource",
     'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"', "DDLS/DF", "application/*", ""),
    ("DDLX", "/sap/bc/adt/ddic/ddlx/sources", "ddlx:ddlxSource",
     'xmlns:ddlx="http://www.sap.com/adt/ddic/ddlxsources"', "DDLX/EX", "application/*", ""),
    ("DCLS", "/sap/bc/adt/acm/dcl/sources", "dcl:dclSource",
     'xmlns:dcl="http://www.sap.com/adt/acm/dclsources"', "DCLS/DL", "application/*", ""),
    ("DTEL", "/sap/bc/adt/ddic/dataelements", "blue:wbobj",
     'xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel"', "DTEL/DE", "application/*", ""),
    ("DOMA", "/sap/bc/adt/ddic/domains", "doma:wbobj",
     'xmlns:doma="http://www.sap.com/wbobj/dictionary/doma"', "DOMA/DD", "application/*", ""),
    ("BDEF", "/sap/bc/adt/bo/behaviordefinitions", "blue:blueSource",
     'xmlns:blue="http://www.sap.com/wbobj/blue"', "BDEF/BDO",
     "application/vnd.sap.adt.blues.v1+xml", ""),
    ("CLAS", "/sap/bc/adt/oo/classes", "class:abapClass",
     'xmlns:class="http://www.sap.com/adt/oo/classes"', "CLAS/OC", "application/*", ""),
    ("SRVD", "/sap/bc/adt/ddic/srvd/sources", "srvd:srvdSource",
     'xmlns:srvd="http://www.sap.com/adt/ddic/srvdsources"', "SRVD/SRV", "application/*",
     'srvd:srvdSourceType="S"'),
]


def body(root, ns, name, adt_type, extra):
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

    for label, path, root, ns, at, ct, extra in TYPES:
        name = f"ZZ{label}{SFX}"
        url = f"{base_url(s.url)}{path}"
        if TR:
            url += f"?corrNr={quote(TR, safe='')}"
        b = body(root, ns, name, at, extra)
        r = adt._post(s, url, ct, b.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        print(f"{label:5s} {name:12s} -> HTTP {r.status_code} {'OK' if ok else ''}")
        if not ok:
            print("    ", r.text[:240])


if __name__ == "__main__":
    main()
