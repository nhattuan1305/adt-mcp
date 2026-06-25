# clone_package Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm MCP tool `clone_package` nhân bản mọi object trong một package SAP sang package đích (đã tồn tại), thêm suffix `_VN` vào mọi tên và rewrite tham chiếu chéo trong source để bản clone trỏ vào nhau, rồi mass-activate ở cuối.

**Architecture:** Logic chính nằm trong `ADTClient.clone_package()` (orchestration) tái sử dụng `list_package`/`get_source`/`get_class_include`/`create_object`/`update_source`. Hai helper thuần (`build_rename_map`, `rewrite_references`) tách riêng để test dễ. Thêm `activate_many` cho mass-activation và mở rộng `object_root_path` cho SRVB. Tool đăng ký trong `server.py`.

**Tech Stack:** Python 3, FastMCP, httpx (test bằng `httpx.MockTransport`), pytest, xml.etree.ElementTree, re.

**Spec:** [docs/superpowers/specs/2026-06-25-clone-package-tool-design.md](../specs/2026-06-25-clone-package-tool-design.md)

---

## File Structure

| File | Trách nhiệm | Thay đổi |
|---|---|---|
| `src/adt_mcp/adt_client.py` | ADT logic | + hằng `CLONE_ORDER`, `SKIP_CLONE_TYPES`; + helper thuần `clone_short_type`, `build_rename_map`, `rewrite_references`; + method `activate_many`, `clone_package`; mở rộng `object_root_path` cho SRVB |
| `src/adt_mcp/server.py` | MCP tool wiring | + tool `clone_package`; thêm `"clone_package"` vào `CORE_TOOLS` |
| `tests/test_clone.py` | Test mới | toàn bộ test cho helper + orchestration |
| `tests/test_server.py` | Test registration | + 1 test `clone_package` đăng ký được |

Lưu ý: `clone_package` nhận **2 đối tượng `System`** (nguồn + đích) đã được `server.py` resolve, cho phép cross-system.

---

## Task 1: Helper thuần `build_rename_map` + `rewrite_references`

Đây là yêu cầu cốt lõi (rewrite tham chiếu chéo). Làm trước, TDD.

**Files:**
- Modify: `src/adt_mcp/adt_client.py` (thêm `import re` nếu chưa có; thêm helper ở khu vực hàm module-level, ngay sau `OBJECT_TYPE_ALIASES` ~ dòng 51)
- Test: `tests/test_clone.py` (tạo mới)

- [ ] **Step 1: Kiểm tra `re` đã import chưa**

Run: `grep -n "^import re" src/adt_mcp/adt_client.py`
Nếu không có dòng nào, thêm `import re` vào khối import đầu file.

- [ ] **Step 2: Viết test thất bại cho 2 helper**

Tạo `tests/test_clone.py`:

```python
from adt_mcp.adt_client import build_rename_map, rewrite_references


def test_build_rename_map_uppercases_and_suffixes():
    m = build_rename_map(["zi_fun_mf902", "ZC_FUN_MF902"], "_VN")
    assert m == {"ZI_FUN_MF902": "ZI_FUN_MF902_VN",
                 "ZC_FUN_MF902": "ZC_FUN_MF902_VN"}


def test_rewrite_reference_in_dependent_source():
    # ZC_FUN_MF902 (consumption) đọc từ ZI_FUN_MF902 (interface view).
    # Sau clone, bản con phải trỏ sang tên _VN của bản cha.
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
    assert "I_BUSINESSPARTNER" in out          # không nằm trong map → giữ nguyên
    assert "I_BUSINESSPARTNER_VN" not in out


def test_rewrite_is_case_insensitive():
    m = build_rename_map(["ZI_FUN_MF902"], "_VN")
    out = rewrite_references("from zi_fun_mf902", m)
    assert "zi_fun_mf902_VN" in out or "ZI_FUN_MF902_VN" in out.upper()


def test_rewrite_longest_name_first_no_prefix_collision():
    # ZI_FUN và ZI_FUN_MF902 cùng tồn tại; không được nuốt tiền tố.
    m = build_rename_map(["ZI_FUN", "ZI_FUN_MF902"], "_VN")
    out = rewrite_references("a ZI_FUN_MF902 b ZI_FUN c", m)
    assert "ZI_FUN_MF902_VN" in out
    assert "ZI_FUN_VN c" in out
    assert "ZI_FUN_MF902_VN_VN" not in out      # không double-suffix
```

- [ ] **Step 3: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_clone.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_rename_map'`

- [ ] **Step 4: Cài đặt 2 helper thuần**

Thêm vào `src/adt_mcp/adt_client.py` ngay sau `OBJECT_TYPE_ALIASES = {"STRUCT": "STRU"}`:

```python
def build_rename_map(names: list[str], suffix: str) -> dict[str, str]:
    """{TÊN_GỐC.upper(): TÊN_GỐC.upper()+suffix.upper()} cho clone đổi tên."""
    suf = (suffix or "").upper()
    return {n.upper(): n.upper() + suf for n in names}


def rewrite_references(source: str, rename_map: dict[str, str]) -> str:
    """Thay thế các tên trong rename_map bằng tên đích, so khớp theo biên từ,
    không phân biệt hoa/thường. Xử lý tên dài trước để tránh trùng tiền tố
    (vd ZI_FUN_MF902 trước ZI_FUN)."""
    if not source or not rename_map:
        return source
    for old in sorted(rename_map, key=len, reverse=True):
        source = re.sub(rf"\b{re.escape(old)}\b", rename_map[old],
                        source, flags=re.IGNORECASE)
    return source
```

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `python -m pytest tests/test_clone.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/adt_mcp/adt_client.py tests/test_clone.py
git commit -m "feat(clone): pure helpers build_rename_map + rewrite_references"
```

---

## Task 2: Phân loại type + thứ tự phụ thuộc

**Files:**
- Modify: `src/adt_mcp/adt_client.py` (thêm hằng + helper `clone_short_type` cạnh helper Task 1)
- Test: `tests/test_clone.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_clone.py`:

```python
from adt_mcp.adt_client import clone_short_type, CLONE_ORDER, SKIP_CLONE_TYPES


def test_clone_short_type_strips_subtype():
    assert clone_short_type("DDLS/DF") == "DDLS"
    assert clone_short_type("CLAS/OC") == "CLAS"
    assert clone_short_type("srvb/svb") == "SRVB"


def test_clone_order_and_skip_sets():
    # TABL phải đứng trước DDLS; SRVD trước SRVB.
    assert CLONE_ORDER.index("TABL") < CLONE_ORDER.index("DDLS")
    assert CLONE_ORDER.index("SRVD") < CLONE_ORDER.index("SRVB")
    assert "DTEL" in SKIP_CLONE_TYPES and "DOMA" in SKIP_CLONE_TYPES
    assert "SRVB" not in SKIP_CLONE_TYPES        # SRVB được clone
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_clone.py -k "short_type or clone_order" -v`
Expected: FAIL — `ImportError: cannot import name 'clone_short_type'`

- [ ] **Step 3: Cài đặt hằng + helper**

Thêm vào `src/adt_mcp/adt_client.py` cạnh helper Task 1:

```python
# Thứ tự tạo theo phụ thuộc (DOMA→...→SRVB). Activate dồn ở cuối nên thứ tự
# trong cùng nhóm (vd nhiều DDLS) không cần hoàn hảo.
CLONE_ORDER = ["DOMA", "DTEL", "TABL", "DDLS", "DDLX", "DCLS",
               "INTF", "CLAS", "BDEF", "SRVD", "SRVB"]

# Type chỉ tạo được shell (không copy được nội dung) → bỏ qua ở v1.
SKIP_CLONE_TYPES = {"DTEL", "DOMA"}


def clone_short_type(node_type: str) -> str:
    """OBJECT_TYPE từ nodestructure ('DDLS/DF') → key CREATE_TYPES ('DDLS')."""
    return (node_type or "").split("/")[0].upper()
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `python -m pytest tests/test_clone.py -k "short_type or clone_order" -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/adt_mcp/adt_client.py tests/test_clone.py
git commit -m "feat(clone): type classification + dependency order constants"
```

---

## Task 3: `activate_many` + hỗ trợ SRVB trong `object_root_path`

**Files:**
- Modify: `src/adt_mcp/adt_client.py` (mở rộng `object_root_path` ~ dòng 56; thêm method `activate_many` ngay sau `activate` ~ dòng 1808)
- Test: `tests/test_clone.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_clone.py`:

```python
import httpx
from adt_mcp.adt_client import ADTClient, object_root_path
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
    assert len(calls["bodies"]) == 1                 # một POST duy nhất
    body = calls["bodies"][0]
    assert 'adtcore:name="ZI_X_VN"' in body
    assert 'adtcore:name="ZC_X_VN"' in body


def test_activate_many_empty_is_ok():
    out = _client(lambda r: httpx.Response(404)).activate_many(_sys(), [])
    assert out == "OK"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_clone.py -k "root_path_supports_srvb or activate_many" -v`
Expected: FAIL — `object_root_path("SRVB"...)` raises ValueError / `activate_many` không tồn tại

- [ ] **Step 3: Mở rộng `object_root_path` cho SRVB**

Trong `object_root_path` (`src/adt_mcp/adt_client.py`), ngay sau khối `if ot == "FUGR":` thêm:

```python
    if ot == "SRVB":
        return f"/sap/bc/adt/businessservices/bindings/{name.upper()}"
```

- [ ] **Step 4: Thêm method `activate_many`**

Thêm ngay sau method `activate` (kết thúc ~ dòng 1808) trong class `ADTClient`:

```python
    def activate_many(self, system: System,
                      refs: list[tuple[str, str, str | None]]) -> str:
        """Activate nhiều object trong MỘT call để SAP tự giải quyết phụ thuộc.
        refs: list (object_type, name, function_group)."""
        if not refs:
            return "OK"
        parts = []
        for ot, name, fg in refs:
            try:
                rp = object_root_path(ot, name, fg)
            except ValueError as e:
                return f"Error: {e}"
            parts.append(
                f'<adtcore:objectReference adtcore:uri="{rp}" '
                f'adtcore:name="{name.upper()}"/>')
        body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<adtcore:objectReferences '
                f'xmlns:adtcore="http://www.sap.com/adt/core">'
                f'{"".join(parts)}'
                f'</adtcore:objectReferences>').encode("utf-8")
        url = (f"{base_url(system.url)}/sap/bc/adt/activation"
               f"?method=activate&preauditRequested=true")
        try:
            resp = self._post(system, url, "application/xml",
                              body, "application/xml")
        except httpx.HTTPError as e:
            return f"Error: activate request failed: {e}"
        if resp.status_code not in (200, 202):
            return (f"Error: activate failed (HTTP {resp.status_code}): "
                    f"{resp.text[:300]}")
        return parse_activation(resp.content)
```

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `python -m pytest tests/test_clone.py -k "root_path_supports_srvb or activate_many" -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/adt_mcp/adt_client.py tests/test_clone.py
git commit -m "feat(clone): activate_many + object_root_path SRVB support"
```

---

## Task 4: `clone_package` orchestration — dry-run + execute

**Files:**
- Modify: `src/adt_mcp/adt_client.py` (thêm method `clone_package` + helper `_read_srvb_servicedef` sau `clone_package`)
- Test: `tests/test_clone.py`

- [ ] **Step 1: Viết test dry-run (plan) — thất bại**

Thêm vào `tests/test_clone.py`:

```python
_NODES = (
    b'<root xmlns:adtcore="x">'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DDLS/DF</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZI_FUN_MF902</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/ddl/sources/zi_fun_mf902</OBJECT_URI>'
    b'<DESCRIPTION>iface</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DDLS/DF</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZC_FUN_MF902</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/ddl/sources/zc_fun_mf902</OBJECT_URI>'
    b'<DESCRIPTION>cons</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'<SEU_ADT_REPOSITORY_OBJ_NODE><OBJECT_TYPE>DOMA/DD</OBJECT_TYPE>'
    b'<OBJECT_NAME>ZD_STATUS</OBJECT_NAME>'
    b'<OBJECT_URI>/sap/bc/adt/ddic/domains/zd_status</OBJECT_URI>'
    b'<DESCRIPTION>dom</DESCRIPTION></SEU_ADT_REPOSITORY_OBJ_NODE>'
    b'</root>')


def _nodestructure_handler(extra=None):
    def handler(req):
        u = str(req.url)
        if req.method == "POST" and "nodestructure" in u:
            return httpx.Response(200, content=_NODES,
                                  headers={"content-type": "application/xml"})
        if extra:
            r = extra(req)
            if r is not None:
                return r
        return httpx.Response(404, text="nf")
    return handler


def test_clone_package_dry_run_lists_plan_and_skips_doma():
    c = _client(_nodestructure_handler())
    out = c.clone_package(_sys(), _sys(), "ZRAP_FUN_MF902",
                          "ZRAP_FUN_MF902_VN", suffix="_VN", dry_run=True)
    assert "ZI_FUN_MF902 -> ZI_FUN_MF902_VN" in out
    assert "ZC_FUN_MF902 -> ZC_FUN_MF902_VN" in out
    assert "ZD_STATUS" in out and "skip" in out.lower()      # DOMA bị skip
    assert "Dry run" in out
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_clone.py -k "dry_run_lists_plan" -v`
Expected: FAIL — `clone_package` không tồn tại

- [ ] **Step 3: Cài đặt `clone_package` (đủ cho dry-run, đã gồm nhánh execute)**

Thêm method vào class `ADTClient` (đặt sau `create_object`). Code đầy đủ cho cả dry-run và execute:

```python
    def clone_package(self, source: System, target: System,
                      source_package: str, target_package: str,
                      suffix: str = "_VN", dry_run: bool = True,
                      transport: str | None = None) -> str:
        """Nhân bản object của source_package sang target_package (đã tồn tại),
        thêm suffix vào mọi tên, rewrite tham chiếu chéo, activate dồn cuối."""
        objs = self.list_package(source, source_package)
        if isinstance(objs, str):
            return objs
        if not objs:
            return f"(no objects in package {source_package.upper()})"

        # Phân loại
        cloneable, skipped = [], []
        for o in objs:
            short = clone_short_type(o["type"])
            if short == "DEVC":
                continue
            if short not in CREATE_TYPES:
                skipped.append((o, short, "type không hỗ trợ create"))
            elif short in SKIP_CLONE_TYPES:
                skipped.append((o, short, "type chỉ tạo shell (v1)"))
            else:
                cloneable.append((o, short))

        rename_map = build_rename_map([o["name"] for o, _ in cloneable], suffix)

        # Validate độ dài tên đích
        errors = []
        for o, short in list(cloneable):
            if len(rename_map[o["name"].upper()]) > 30:
                errors.append((o, short, "tên đích > 30 ký tự"))
        err_names = {o["name"] for o, _, _ in errors}
        cloneable = [(o, s) for o, s in cloneable if o["name"] not in err_names]

        # Sắp theo thứ tự phụ thuộc
        cloneable.sort(key=lambda os: CLONE_ORDER.index(os[1]))

        # In kế hoạch
        lines = [f"Plan: clone {source_package.upper()} -> "
                 f"{target_package.upper()} (suffix={suffix}), "
                 f"{len(cloneable)} clone, {len(skipped)} skip, "
                 f"{len(errors)} error"]
        for o, short in cloneable:
            lines.append(f"  ✓  {short:<5} {o['name']} -> "
                         f"{rename_map[o['name'].upper()]}")
        for o, short, why in skipped + errors:
            lines.append(f"  ⊘  {short:<5} {o['name']} -> (skip: {why})")

        if dry_run:
            lines.append("Dry run — chưa ghi gì. Đặt dry_run=false để thực thi.")
            return "\n".join(lines)

        gate = check_write(target, target_package)
        if gate:
            return gate

        created_refs: list[tuple[str, str, str | None]] = []
        results = []
        for o, short in cloneable:
            name, new = o["name"], rename_map[o["name"].upper()]
            desc = o.get("description") or f"Clone of {name}"
            res = self._clone_one(source, target, short, name, new,
                                  target_package, desc, rename_map,
                                  o.get("uri", ""), transport)
            results.append(f"  {short} {new}: {res}")
            if res.startswith("OK"):
                created_refs.append((short, new, None))

        act = self.activate_many(target, created_refs)
        ok = sum(1 for r in results if ": OK" in r)
        return ("\n".join(lines[1:]) + "\n--- Execute ---\n"
                + "\n".join(results)
                + f"\nActivate ({len(created_refs)} objects): {act}"
                + f"\nClone complete: {ok} success, "
                + f"{len(skipped)+len(errors)} skipped, "
                + f"{len(cloneable)-ok} failed")

    def _clone_one(self, source: System, target: System, short: str,
                   name: str, new: str, package: str, desc: str,
                   rename_map: dict[str, str], uri: str,
                   transport: str | None) -> str:
        if short == "SRVB":
            sd = self._read_srvb_servicedef(source, uri)
            if sd is None:
                return "FAILED: không đọc được service definition của binding"
            sd_name, version = sd
            sd_new = rename_map.get(sd_name.upper(), sd_name.upper())
            return self.create_object(target, "SRVB", new, package, desc,
                                      service_definition=sd_new,
                                      binding_version=version,
                                      transport=transport)
        if short == "CLAS":
            shell = self.create_object(target, "CLAS", new, package, desc,
                                       transport=transport)
            if not shell.startswith("OK"):
                return shell
            for inc in ("definitions", "implementations", "macros",
                        "testclasses", "main"):
                src = (self.get_class_include(source, name, inc)
                       if inc != "main"
                       else self.get_source(source, "CLAS", name))
                if src.startswith("Error:") or not src.strip():
                    continue
                w = self.update_class_include(
                    target, new, inc, rewrite_references(src, rename_map),
                    transport, activate=False)
                if not w.startswith("OK"):
                    return f"FAILED include {inc}: {w}"
            return "OK"
        # Object có source: tạo shell rồi ghi source (inactive)
        src = self.get_source(source, short, name)
        if src.startswith("Error:"):
            return f"FAILED read source: {src}"
        shell = self.create_object(target, short, new, package, desc,
                                   transport=transport)
        if not shell.startswith("OK"):
            return shell
        return self.update_source(target, short, new,
                                  rewrite_references(src, rename_map),
                                  transport, activate=False)

    def _read_srvb_servicedef(self, system: System,
                              uri: str) -> tuple[str, str] | None:
        """Đọc binding → (tên service definition, binding version V2/V4)."""
        url = f"{base_url(system.url)}{uri}"
        try:
            resp = self._get(system, url, "application/xml")
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or is_login_page(resp):
            return None
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return None
        sd_name, version = None, "V2"
        for el in root.iter():
            ln = _localname(el.tag)
            attrs = {_localname(k): v for k, v in el.attrib.items()}
            if ln == "serviceDefinition" and attrs.get("name"):
                sd_name = attrs["name"]
            if ln == "binding" and attrs.get("version"):
                version = attrs["version"]
        if not sd_name:
            return None
        return sd_name, version
```

- [ ] **Step 4: Chạy test dry-run để xác nhận PASS**

Run: `python -m pytest tests/test_clone.py -k "dry_run_lists_plan" -v`
Expected: 1 passed

- [ ] **Step 5: Viết test execute (rewrite áp dụng đúng vào source con)**

Thêm vào `tests/test_clone.py`:

```python
def test_clone_package_execute_rewrites_dependent_source():
    """ZC_FUN_MF902 đọc từ ZI_FUN_MF902; sau clone, source ZC_..._VN gửi lên
    SAP phải chứa ZI_FUN_MF902_VN (trỏ vào bản clone, không phải bản gốc)."""
    puts = {}

    def extra(req):
        u = str(req.url)
        if req.method == "GET" and "discovery" in u:
            return httpx.Response(200, headers={"x-csrf-token": "T"})
        # get_source của 2 view nguồn
        if req.method == "GET" and "zi_fun_mf902/source/main" in u:
            return httpx.Response(200, text="define view entity ZI_FUN_MF902 "
                                  "as select from ztab { key id }")
        if req.method == "GET" and "zc_fun_mf902/source/main" in u:
            return httpx.Response(200, text="define view entity ZC_FUN_MF902 "
                                  "as select from ZI_FUN_MF902 { key id }")
        if req.method == "POST" and u.endswith("/ddic/ddl/sources"):
            return httpx.Response(201, text="")        # create shell
        if req.method == "GET" and "ddl/sources/" in u and "/source/main" not in u:
            return httpx.Response(                       # object_package
                200, headers={"content-type": "application/xml"},
                content=b'<r><adtcore:packageRef xmlns:adtcore="x" '
                        b'adtcore:name="ZRAP_FUN_MF902_VN"/></r>')
        if "_action=LOCK" in u:
            return httpx.Response(
                200, headers={"content-type": "application/xml"},
                content=b'<a><DATA><LOCK_HANDLE>LH</LOCK_HANDLE></DATA></a>')
        if req.method == "PUT":
            puts[str(req.url)] = req.content.decode()
            return httpx.Response(200, text="")
        if "_action=UNLOCK" in u:
            return httpx.Response(200, text="")
        if "activation" in u:
            return httpx.Response(200, content=b"<messages/>")
        return None

    c = _client(_nodestructure_handler(extra))
    out = c.clone_package(_sys(write_packages=["ZRAP_*"]),
                          _sys(write_packages=["ZRAP_*"]),
                          "ZRAP_FUN_MF902", "ZRAP_FUN_MF902_VN",
                          suffix="_VN", dry_run=False)
    body = "\n".join(puts.values())
    assert "ZI_FUN_MF902_VN" in body
    assert "from ZI_FUN_MF902 {" not in body          # bản gốc đã bị thay
    assert "Clone complete" in out
```

- [ ] **Step 6: Chạy test execute**

Run: `python -m pytest tests/test_clone.py -k "execute_rewrites_dependent" -v`
Expected: 1 passed (nếu fail, kiểm tra routing handler khớp URL ADT)

- [ ] **Step 7: Chạy toàn bộ test_clone.py**

Run: `python -m pytest tests/test_clone.py -v`
Expected: tất cả pass

- [ ] **Step 8: Commit**

```bash
git add src/adt_mcp/adt_client.py tests/test_clone.py
git commit -m "feat(clone): clone_package orchestration (dry-run + execute + SRVB)"
```

---

## Task 5: Đăng ký MCP tool `clone_package`

**Files:**
- Modify: `src/adt_mcp/server.py` (thêm `"clone_package"` vào `CORE_TOOLS` ~ dòng 55; thêm tool sau `create_object` ~ dòng 382)
- Test: `tests/test_server.py`

- [ ] **Step 1: Viết test đăng ký — thất bại**

Thêm vào `tests/test_server.py`:

```python
def test_clone_package_tool_registered(tmp_path):
    reg = _reg(tmp_path)
    adt = ADTClient(httpx.Client())
    mcp = build_server(reg, adt)
    tools = asyncio.run(mcp.list_tools())
    assert any(t.name == "clone_package" for t in tools)
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_server.py -k clone_package -v`
Expected: FAIL — không có tool `clone_package`

- [ ] **Step 3: Thêm `"clone_package"` vào CORE_TOOLS**

Trong `src/adt_mcp/server.py`, sửa tập `CORE_TOOLS` (dòng ~55) thêm phần tử:

```python
    "syntax_check", "run_unit_tests", "data_preview", "refresh_cookies_for",
    "clone_package",
```

- [ ] **Step 4: Thêm tool `clone_package`**

Thêm ngay sau hàm `create_object` (trước `refresh_cookies_for`) trong `build_server`:

```python
    @tool("clone_package")
    def clone_package(system: str, source_package: str, target_package: str,
                      target_system: str | None = None, suffix: str = "_VN",
                      dry_run: bool = True,
                      transport: str | None = None) -> str:
        """Clone mọi object của source_package sang target_package (PHẢI tồn tại sẵn),
        thêm suffix (mặc định _VN) vào mọi tên và sửa tham chiếu chéo trong source.
        dry_run=True (mặc định) chỉ in kế hoạch. target_system bỏ trống = cùng system.
        Bỏ qua DTEL/DOMA (chỉ tạo shell). Cần allow_write trên system đích."""
        src, err = _resolve(system)
        if err:
            return err
        tgt, err2 = (_resolve(target_system) if target_system else (src, None))
        if err2:
            return err2
        return adt.clone_package(src, tgt, source_package, target_package,
                                 suffix, dry_run, transport)
```

- [ ] **Step 5: Chạy test đăng ký để xác nhận PASS**

Run: `python -m pytest tests/test_server.py -k clone_package -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add src/adt_mcp/server.py tests/test_server.py
git commit -m "feat(clone): register clone_package MCP tool"
```

---

## Task 6: Cập nhật tài liệu + chạy full suite

**Files:**
- Modify: `README.md` và/hoặc `docs/adt-mcp-overview.md` (nếu có liệt kê tool)

- [ ] **Step 1: Tìm danh sách tool trong docs**

Run: `grep -rn "create_object" README.md docs/adt-mcp-overview.md`
Nếu có bảng/danh sách tool, thêm dòng cho `clone_package` mô tả: "Clone toàn bộ object của package sang package đích, thêm suffix _VN + sửa tham chiếu chéo".

- [ ] **Step 2: Chạy toàn bộ test suite**

Run: `python -m pytest -q`
Expected: tất cả pass (gồm test cũ + test_clone.py mới + test_server.py)

- [ ] **Step 3: Commit**

```bash
git add README.md docs/adt-mcp-overview.md
git commit -m "docs: document clone_package tool"
```

---

## Self-Review Notes (đã kiểm)

- **Spec coverage:** suffix `_VN` (Task 1/4), rewrite tham chiếu chéo + ví dụ ZRAP_FUN_MF902 (Task 1 test + Task 4 Step 5), cross-system 2×System (Task 4/5), dry_run mặc định (Task 4), activate dồn cuối (Task 3 + Task 4), thứ tự phụ thuộc (Task 2/4), chỉ 1 package phẳng (`list_package` không recursive), SRVB clone + remap SD (Task 4 `_clone_one`/`_read_srvb_servicedef`), DTEL/DOMA skip (Task 2/4), validate độ dài tên (Task 4), gate allow_write (Task 4).
- **Type consistency:** `build_rename_map`, `rewrite_references`, `clone_short_type`, `CLONE_ORDER`, `SKIP_CLONE_TYPES`, `activate_many`, `clone_package`, `_clone_one`, `_read_srvb_servicedef` dùng nhất quán giữa các task. `create_object`/`update_source`/`update_class_include` dùng đúng chữ ký hiện có (`activate=False` để defer). Key map luôn `.upper()`.
- **Điểm cần xác nhận khi execute:** kích hoạt SRVB qua endpoint activation chung (Task 3) — nếu SAP yêu cầu publish riêng cho binding, ghi nhận và xử lý ở bước thực thi.
