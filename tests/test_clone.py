from adt_mcp.adt_client import build_rename_map, rewrite_references


def test_build_rename_map_uppercases_and_suffixes():
    m = build_rename_map(["zi_fun_mf902", "ZC_FUN_MF902"], "_VN")
    assert m == {"ZI_FUN_MF902": "ZI_FUN_MF902_VN",
                 "ZC_FUN_MF902": "ZC_FUN_MF902_VN"}


def test_rewrite_reference_in_dependent_source():
    # ZC_FUN_MF902 (consumption) reads from ZI_FUN_MF902 (interface view).
    # After clone, the child must point to the _VN name of the parent.
    m = build_rename_map(["ZI_FUN_MF902", "ZC_FUN_MF902"], "_VN")
    src = "define view entity ZC_FUN_MF902 as select from ZI_FUN_MF902 { key id }"
    out = rewrite_references(src, m)
    assert "from ZI_FUN_MF902_VN" in out
    assert "ZC_FUN_MF902_VN as select" in out


def test_rewrite_leaves_external_names_untouched():
    m = build_rename_map(["ZI_FUN_MF902"], "_VN")
    src = "select from ZI_FUN_MF902 association to I_BUSINESSPARTNER"
    out = rewrite_references(src, m)
    assert "ZI_FUN_MF902_VN" in out
    assert "I_BUSINESSPARTNER" in out
    assert "I_BUSINESSPARTNER_VN" not in out


def test_rewrite_is_case_insensitive():
    m = build_rename_map(["ZI_FUN_MF902"], "_VN")
    out = rewrite_references("from zi_fun_mf902", m)
    assert out == "from ZI_FUN_MF902_VN"


def test_rewrite_longest_name_first_no_prefix_collision():
    m = build_rename_map(["ZI_FUN", "ZI_FUN_MF902"], "_VN")
    out = rewrite_references("a ZI_FUN_MF902 b ZI_FUN c", m)
    assert "ZI_FUN_MF902_VN" in out
    assert "ZI_FUN_VN c" in out
    assert "ZI_FUN_MF902_VN_VN" not in out


import httpx
from adt_mcp.adt_client import (clone_short_type, CLONE_ORDER, SKIP_CLONE_TYPES,
                                 object_root_path, ADTClient)
from adt_mcp.registry import System


def _sys(**kw):
    base = dict(name="dev", url="https://h.example", client="080",
                language="EN", auth="basic", username="u", password="p",
                cookie_file=None, cookie_string=None,
                allow_write=True, write_packages=None)
    base.update(kw)
    return System(**base)


def _client(handler):
    return ADTClient(httpx.Client(transport=httpx.MockTransport(handler)))


def test_clone_short_type_strips_subtype():
    assert clone_short_type("DDLS/DF") == "DDLS"
    assert clone_short_type("CLAS/OC") == "CLAS"
    assert clone_short_type("srvb/svb") == "SRVB"


def test_clone_order_and_skip_sets():
    # TABL must come before DDLS; SRVD before SRVB.
    assert CLONE_ORDER.index("TABL") < CLONE_ORDER.index("DDLS")
    assert CLONE_ORDER.index("SRVD") < CLONE_ORDER.index("SRVB")
    assert "DTEL" in SKIP_CLONE_TYPES and "DOMA" in SKIP_CLONE_TYPES
    assert "SRVB" not in SKIP_CLONE_TYPES        # SRVB is cloned


def test_object_root_path_supports_srvb():
    assert object_root_path("SRVB", "zsb") == \
        "/sap/bc/adt/businessservices/bindings/ZSB"


def test_activate_many_sends_all_references_in_one_post():
    calls = {"bodies": []}

    def handler(req):
        u = str(req.url)
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        if "activation" in u:
            calls["bodies"].append(req.content.decode())
            return httpx.Response(200, content=b"<messages/>")
        return httpx.Response(404)

    out = _client(handler).activate_many(
        _sys(), [("DDLS", "ZI_X_VN", None), ("DDLS", "ZC_X_VN", None)])
    assert out == "OK"
    assert len(calls["bodies"]) == 1
    body = calls["bodies"][0]
    assert 'adtcore:name="ZI_X_VN"' in body
    assert 'adtcore:name="ZC_X_VN"' in body


def test_activate_many_empty_is_ok():
    out = _client(lambda r: httpx.Response(404)).activate_many(_sys(), [])
    assert out == "OK"
