"""Probe which create body variant the ABAP Cloud ST actually accepts.
Run on the VM:  cd C:\\adt-mcp ; git pull ; python diag_create2.py

Tries several CLAS bodies (and one DDLS) against the live system and prints
the HTTP status + short response for each. A 200/201 = accepted (and the
object really gets created in $TMP, throwaway). Distinct names per variant.
"""
import os
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import ADTClient, base_url

SYS = os.environ.get("DIAG_SYS", "VNEXT")
ALV = 'adtcore:abapLanguageVersion="cloudDevelopment"'


def clas_body(name, *, alv=False, classattrs=False, mastersystem=False):
    ns = ['xmlns:class="http://www.sap.com/adt/oo/classes"',
          'xmlns:adtcore="http://www.sap.com/adt/core"']
    attrs = ['adtcore:description="diag"', f'adtcore:name="{name}"',
             'adtcore:type="CLAS/OC"', 'adtcore:language="EN"',
             'adtcore:masterLanguage="EN"', 'adtcore:responsible="CB0000000000"']
    if mastersystem:
        attrs.append('adtcore:masterSystem="PKO"')
    if alv:
        attrs.append(ALV)
    if classattrs:
        ns += ['xmlns:abapoo="http://www.sap.com/adt/oo"',
               'xmlns:abapsource="http://www.sap.com/adt/abapsource"']
        attrs += ['class:final="true"', 'class:visibility="public"',
                  'class:category="generalObjectType"',
                  'abapoo:modeled="false"',
                  'abapsource:fixPointArithmetic="true"',
                  'abapsource:activeUnicodeCheck="false"']
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<class:abapClass {" ".join(ns)} {" ".join(attrs)}>\n'
            '  <adtcore:packageRef adtcore:name="$TMP"/>\n'
            '</class:abapClass>')


def ddls_body(name, *, alv=False):
    attrs = ['adtcore:description="diag"', f'adtcore:name="{name}"',
             'adtcore:type="DDLS/DF"', 'adtcore:language="EN"',
             'adtcore:masterLanguage="EN"', 'adtcore:responsible="CB0000000000"']
    if alv:
        attrs.append(ALV)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ddl:ddlSource xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'{" ".join(attrs)}>\n'
            '  <adtcore:packageRef adtcore:name="$TMP"/>\n'
            '</ddl:ddlSource>')


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(path).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))

    def post(label, url_path, body):
        url = f"{base_url(s.url)}{url_path}"
        r = adt._post(s, url, "application/*", body.encode("utf-8"),
                      "application/*")
        msg = r.text
        if r.status_code not in (200, 201):
            i = msg.find("XML_OFFSET")
            tail = msg[i:i + 40] if i >= 0 else msg[:160]
        else:
            tail = "CREATED OK"
        print(f"{label:42s} -> HTTP {r.status_code}  {tail}")

    print(f"system={s.name} language={s.language!r}")
    print("CLAS variants " + "-" * 50)
    post("V0 baseline", "/sap/bc/adt/oo/classes",
         clas_body("ZZDIAGV0"))
    post("V1 +abapLanguageVersion", "/sap/bc/adt/oo/classes",
         clas_body("ZZDIAGV1", alv=True))
    post("V2 +alv +classattrs", "/sap/bc/adt/oo/classes",
         clas_body("ZZDIAGV2", alv=True, classattrs=True))
    post("V3 +alv +classattrs +masterSystem", "/sap/bc/adt/oo/classes",
         clas_body("ZZDIAGV3", alv=True, classattrs=True, mastersystem=True))
    print("DDLS variants " + "-" * 50)
    post("D0 baseline", "/sap/bc/adt/ddic/ddl/sources",
         ddls_body("ZZDIAGD0"))
    post("D1 +abapLanguageVersion", "/sap/bc/adt/ddic/ddl/sources",
         ddls_body("ZZDIAGD1", alv=True))


if __name__ == "__main__":
    main()
