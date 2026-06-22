"""Verify abapLanguageVersion fixes every type; dump FULL errors for failures.
Run on VM:  cd C:\\adt-mcp ; git pull ; python diag_create3.py
"""
import os
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient, base_url, CREATE_TYPES

SYS = os.environ.get("DIAG_SYS", "VNEXT")
ALV = 'adtcore:abapLanguageVersion="cloudDevelopment"'


def body_for(ot, name, *, extra_attrs="", extra_ns=""):
    path, root, ns, adt_type, ct, _ = CREATE_TYPES[ot]
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root} {ns} xmlns:adtcore="http://www.sap.com/adt/core" {extra_ns} '
            f'adtcore:description="diag" adtcore:name="{name}" '
            f'adtcore:type="{adt_type}" adtcore:language="EN" '
            f'adtcore:masterLanguage="EN" {ALV} '
            f'adtcore:responsible="CB0000000000" {extra_attrs}')
    if ot == "SRVD":
        head += ' srvd:srvdSourceType="S"'
    return (head + '>\n'
            f'  <adtcore:packageRef adtcore:name="$TMP"/>\n</{root}>'), path, ct


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(path).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    print(f"system={s.name} language={s.language!r}\n")

    def run(ot, name, full=False, **kw):
        body, p, ct = body_for(ot, name, **kw)
        r = adt._post(s, f"{base_url(s.url)}{p}", "application/*",
                      body.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        print(f"{ot:5s} {name:14s} -> HTTP {r.status_code} "
              f"{'CREATED OK' if ok else ''}")
        if not ok and full:
            print("   FULL:", r.text)
            print("   BODY:", body.replace("\n", " "))

    # the candidate general fix (alv only) across all RAP types
    run("DDLS", "ZZGENDDLS")
    run("DDLX", "ZZGENDDLX")
    run("INTF", "ZZGENINTF")
    run("PROG", "ZZGENPROG")
    run("TABL", "ZZGENTABL")
    run("SRVD", "ZZGENSRVD")
    # CLAS: show full 500 with alv-only, then with class attrs
    print()
    run("CLAS", "ZZGENCLAS1", full=True)
    run("CLAS", "ZZGENCLAS2", full=True,
        extra_ns='xmlns:abapoo="http://www.sap.com/adt/oo" '
                 'xmlns:abapsource="http://www.sap.com/adt/abapsource"',
        extra_attrs='class:final="true" class:visibility="public" '
                    'class:category="generalObjectType" abapoo:modeled="false" '
                    'abapsource:fixPointArithmetic="true" '
                    'abapsource:activeUnicodeCheck="false"')


if __name__ == "__main__":
    main()
