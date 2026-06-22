"""End-to-end check of the PRODUCTION build_creation_body for every create type
(TABL/DDLS/DDLX/DCLS/DTEL/DOMA/BDEF/CLAS/SRVD/SRVB) against a live system.
Creates throwaway shells in DIAG_PKG (default ZRAP_IF_VI901).

Run on VM:  cd C:\\adt-mcp ; git pull ; python verify_create_all.py
Optional:   set DIAG_PKG=...   set DIAG_SYS=...
"""
import os
import time
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import (
    ADTClient, base_url, build_creation_body, CREATE_TYPES)

SYS = os.environ.get("DIAG_SYS", "VNEXT")
PKG = os.environ.get("DIAG_PKG", "ZRAP_IF_VI901")
SFX = str(int(time.time()) % 1000)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    s = SystemRegistry(p).get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    adt._csrf_token(s)
    resp = (s.username or "").upper() or "CB0000000000"
    print(f"system={s.name} pkg={PKG} responsible={resp} suffix={SFX}\n")

    # find an existing service definition to reference from a service binding
    srvd_name = None
    objs = adt.search_objects(s, "Z*", 120)
    if isinstance(objs, list):
        for o in objs:
            if "/ddic/srvd/sources/" in o.get("uri", ""):
                srvd_name = o["uri"].rsplit("/", 1)[-1].upper(); break

    for ot, (path, root, ns, at, ct, sc) in CREATE_TYPES.items():
        if ot in ("PROG", "INTF"):
            continue  # not needed for the RAP/Fiori flow
        name = f"ZZF{ot[:3]}{SFX}"
        kw = {}
        if ot == "SRVB":
            if not srvd_name:
                print(f"{ot:5s} skipped (no existing SRVD to reference)")
                continue
            name = f"ZZFSB{SFX}"
            kw = dict(service_definition=srvd_name, binding_version="V2")
        body = build_creation_body(ot, name, PKG, "diag-final", resp,
                                   service_definition=kw.get("service_definition"),
                                   binding_version=kw.get("binding_version", "V2"),
                                   language=s.language)
        r = adt._post(s, f"{base_url(s.url)}{path}", ct, body.encode("utf-8"), ct)
        ok = r.status_code in (200, 201)
        extra = f" (srvd={srvd_name})" if ot == "SRVB" else ""
        print(f"{ot:5s} {name:12s} -> HTTP {r.status_code} {'OK' if ok else ''}{extra}")
        if not ok:
            print("    ", r.text[:240])


if __name__ == "__main__":
    main()
