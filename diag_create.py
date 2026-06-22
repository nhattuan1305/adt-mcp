"""Diagnostic: inspect the exact create payload, the FULL deserialize error,
and the canonical metadata XML that the ADT ST expects. Run on the VM:

    cd C:\\adt-mcp
    python diag_create.py

Reads systems.json (or $ADT_MCP_SYSTEMS) and uses the stored VNEXT cookies.
Creates only a throwaway CLAS in $TMP (which fails before anything is saved).
"""
import os
import httpx
from adt_mcp.registry import SystemRegistry
from adt_mcp.adt_client import (
    ADTClient, base_url, build_creation_body, CREATE_TYPES)

SYS = os.environ.get("DIAG_SYS", "VNEXT")
EXISTING_CLASS = "ZCL_039_GEN_DATA"   # known-existing class for the structure dump


def main() -> None:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    reg = SystemRegistry(path)
    s = reg.get(SYS)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))

    print("=" * 70)
    print(f"system={s.name} url={s.url} client={s.client} "
          f"language={s.language!r} auth={s.auth}")
    print("=" * 70)

    # 1) the EXACT body our create_object sends for CLAS
    body = build_creation_body("CLAS", "ZZ_DIAG_CLAS1", "$TMP", "diag",
                               (s.username or "").upper() or "CB0000000000",
                               language=s.language)
    print("\n--- [1] create body we POST (CLAS) -------------------------------")
    print(body)

    # 2) attempt the create, print the FULL (untruncated) response
    path_c, root, ns, adt_type, content_type, _ = CREATE_TYPES["CLAS"]
    url = f"{base_url(s.url)}{path_c}"
    resp = adt._post(s, url, "application/*", body.encode("utf-8"), content_type)
    print("\n--- [2] create response (FULL) -----------------------------------")
    print("HTTP", resp.status_code)
    print(resp.text)

    # 3) canonical metadata XML of an EXISTING class = what the ST serializes,
    #    i.e. exactly the structure it expects back on deserialize.
    root_url = (f"{base_url(s.url)}/sap/bc/adt/oo/classes/"
                f"{EXISTING_CLASS.lower()}?sap-client={s.client}")
    for acc in ("application/vnd.sap.adt.oo.classes.v4+xml",
                "application/vnd.sap.adt.oo.classes.v3+xml",
                "application/vnd.sap.adt.oo.classes.v2+xml",
                "application/*"):
        r = adt._get(s, root_url, acc)
        print(f"\n--- [3] GET {EXISTING_CLASS} metadata  Accept={acc}  -> "
              f"HTTP {r.status_code} ---")
        if r.status_code == 200:
            print(r.text[:2000])
            break
        else:
            print(r.text[:300])


if __name__ == "__main__":
    main()
