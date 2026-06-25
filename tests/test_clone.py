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
