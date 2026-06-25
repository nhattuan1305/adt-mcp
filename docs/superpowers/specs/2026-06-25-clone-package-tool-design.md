# Thiết kế: Tool `clone_package` (nhân bản package + đổi tên + rewrite tham chiếu)

- **Ngày:** 2026-06-25
- **Trạng thái:** Draft chờ review
- **Tác giả:** erp_ai_006@vnext.vn (+ Claude)

## 1. Mục tiêu

Thêm một MCP tool `clone_package` vào adt-mcp để **nhân bản toàn bộ object trong một
package SAP sang một package đích đã tồn tại**, tự động:

1. Thêm hậu tố (mặc định `_VN`) vào tên **mọi** object được clone.
2. **Rewrite các tham chiếu chéo trong source**: nếu object A trong package nguồn
   tham chiếu object B (cũng trong package nguồn), thì bản clone A`_VN` phải tham
   chiếu B`_VN` chứ không trỏ về B gốc.
3. Tạo tất cả object ở trạng thái inactive theo thứ tự phụ thuộc, rồi **activate
   toàn bộ một lần ở cuối** để reference chéo resolve đúng.

Tham khảo ý tưởng: lệnh `vsp copy` của project `vibing-steampunk` (deploy nhiều
object vào một package, có dry-run, lọc, tự xử lý theo type). adt-mcp đã có sẵn
hạ tầng cần thiết: `list_package`, `get_source`, `get_class_include`,
`create_object`, `update_source`, `activate`.

## 2. Phạm vi & quyết định đã chốt

| Vấn đề | Quyết định |
|---|---|
| Hệ thống | Hỗ trợ **cả** cùng-system và cross-system (tham số `target_system` tùy chọn). |
| Đổi tên | Thêm **suffix** (mặc định `_VN`) vào mọi object. |
| Package đích | **Phải tồn tại sẵn**. Tool KHÔNG tạo package. |
| Loại object | Toàn bộ bộ RAP. SRVB clone qua xử lý riêng (mục 8). DTEL/DOMA skip (v1). |
| Mô hình chạy | Một tham số `dry_run` (mặc định `True` = chỉ xem kế hoạch). |
| Activate | Tạo hết (inactive) → **mass-activate ở cuối**. |
| Subpackage | **Không** đệ quy — chỉ object trực tiếp trong package nguồn (v1). |
| Rewrite tham chiếu | **Bắt buộc** — xem mục 5. |

### Ngoài phạm vi (v1)
- Đệ quy subpackage.
- Tự tạo package đích.
- Copy đối tượng không phải bộ RAP (báo skip).

## 3. Giao diện tool

```python
clone_package(
    source_system: str,
    source_package: str,                # vd "ZRAP_FUN_MF902"
    target_package: str,                # vd "ZRAP_FUN_MF902_VN" (phải tồn tại)
    target_system: str | None = None,   # None = cùng system nguồn
    suffix: str = "_VN",                # thêm vào MỌI object clone
    dry_run: bool = True,               # mặc định chỉ in kế hoạch
    transport: str | None = None,       # cho package transportable ở đích
) -> str
```

- Đăng ký trong [server.py](../../../src/adt_mcp/server.py) như các write-tool khác,
  thêm tên `"clone_package"` vào tập `CORE_TOOLS`.
- Logic chính: method mới `ADTClient.clone_package(...)` trong
  [adt_client.py](../../../src/adt_mcp/adt_client.py).
- Tuân thủ `check_write`/`allow_write` gate hiện có trên **system đích**.

### Output khi `dry_run=True`
Bảng kế hoạch, mỗi dòng: `STATUS  TYPE   TÊN_NGUỒN -> TÊN_ĐÍCH`, ví dụ:
```
Plan: clone ZRAP_FUN_MF902 -> ZRAP_FUN_MF902_VN (suffix=_VN), 5 objects
  ✓  DDLS   ZI_FUN_MF902      -> ZI_FUN_MF902_VN
  ✓  DDLS   ZC_FUN_MF902      -> ZC_FUN_MF902_VN
  ✓  BDEF   ZI_FUN_MF902      -> ZI_FUN_MF902_VN
  ✓  CLAS   ZBP_FUN_MF902     -> ZBP_FUN_MF902_VN
  ⊘  DOMA   ZD_FUN_STATUS     -> (skip: type không hỗ trợ create source)
Reference rewrite map: ZI_FUN_MF902->ZI_FUN_MF902_VN, ZC_FUN_MF902->...
Dry run — chưa ghi gì. Đặt dry_run=false để thực thi.
```

### Output khi `dry_run=False`
Kết quả từng bước create + ghi source + tổng kết activate:
```
Created+wrote: DDLS ZI_FUN_MF902_VN ... OK
...
Activate (5 objects together): OK
Clone complete: 4 success, 1 skipped, 0 failed
```

## 4. Luồng xử lý

```
1. Resolve source_system, target_system (mặc định = source_system).
2. Kiểm tra allow_write trên target_system; nếu không có -> trả lỗi gate.
3. objs = list_package(source_system, source_package)   # phẳng, không đệ quy
4. Lọc theo CREATE_TYPES; type không hỗ trợ -> đánh dấu skip.
5. Tính rename map: {TÊN_GỐC.upper(): TÊN_GỐC.upper()+suffix.upper()} cho mọi
   object KHÔNG bị skip. Validate độ dài tên đích <= 30 ký tự, vượt -> error.
6. Nếu dry_run: in kế hoạch + rename map rồi return.
7. Sắp object theo thứ tự phụ thuộc (mục 6).
8. Với mỗi object (theo thứ tự):
     a. Đọc source nguồn (get_source; CLAS đọc thêm các include).
     b. Rewrite tham chiếu trong source bằng rename map (mục 5).
     c. create_object(target_system, type, tên_đích, target_package, desc,
        source=rewritten, activate=False)   # tạo inactive
        - CLAS: create shell rồi ghi từng include qua update_class_include(activate=False).
        - SRVB: không ghi source; đọc binding gốc lấy service_definition + binding
          version, map SD qua rename_map, create_object(SRVB, ..., service_definition=...).
9. Mass-activate tất cả object đích vừa tạo trong MỘT call (mục 7).
10. Tổng hợp kết quả trả về.
```

## 5. Rewrite tham chiếu chéo (yêu cầu cốt lõi)

**Bài toán ví dụ:** package `ZRAP_FUN_MF902` có 2 CDS phụ thuộc nhau:
- `ZI_FUN_MF902` (interface view, đọc từ bảng).
- `ZC_FUN_MF902` (consumption view) — bên trong có `... from ZI_FUN_MF902 ...`.

Khi clone sang `ZRAP_FUN_MF902_VN`, source của `ZC_FUN_MF902_VN` **phải** được sửa
thành `... from ZI_FUN_MF902_VN ...`, không được trỏ về `ZI_FUN_MF902` gốc.

**Thuật toán:**
1. Xây `rename_map` từ tất cả object được clone (không gồm object skip).
2. Với mỗi source, thay thế **chỉ** các tên nằm trong `rename_map` (tức object
   thuộc package nguồn). Tên object ngoài package (chuẩn SAP, package khác) giữ nguyên.
3. So khớp **theo biên từ** (word boundary, regex `\b`), **không phân biệt hoa
   thường** (ABAP uppercase), thay thế tên dài trước tên ngắn để tránh trùng tiền tố
   (vd `ZI_FUN_MF902` xử lý trước `ZI_FUN`).
4. Áp dụng cho mọi nơi xuất hiện trong source: định nghĩa CDS (`define view ...`),
   `from`/`association`/`composition`, BDEF (`define behavior for ...`,
   `implementation in class ...`, `with draft`...), SRVD (`expose ... as ...`),
   DDLX annotation, và tên class/interface trong code ABAP.
5. **Tên object trong header/định nghĩa** cũng đổi: vd dòng `define view entity
   ZI_FUN_MF902` -> `define view entity ZI_FUN_MF902_VN` (đã nằm trong rename_map nên
   tự khớp).

**Lưu ý SQL view name (TABL của CDS):** với CDS cũ dùng `@AbapCatalog.sqlViewName`,
giá trị này cũng phải đổi để không trùng — nhưng đó là tên do người dùng tự đặt,
không nằm trong rename_map. v1: nếu phát hiện annotation `sqlViewName` -> cảnh báo
trong kết quả để người dùng tự xử lý (CDS view entity hiện đại không cần sqlViewName).

**Test bắt buộc** (xem mục 9): dựng 2 object giả phụ thuộc nhau, chạy rewrite, assert
source con đã trỏ sang tên `_VN` của object cha.

## 6. Thứ tự phụ thuộc khi tạo

Tạo theo thứ tự để giảm lỗi (dù activate dồn cuối):
```
DOMA -> DTEL -> TABL -> DDLS -> DDLX -> DCLS -> INTF -> CLAS -> BDEF -> SRVD -> SRVB
```
Trong cùng nhóm DDLS (view phụ thuộc view) không tự topo-sort hoàn hảo được; chấp
nhận vì **activate dồn ở cuối** sẽ resolve liên-phụ-thuộc.

## 7. Activate dồn cuối (mass activation)

ADT endpoint `/sap/bc/adt/activation?method=activate` nhận **nhiều**
`adtcore:objectReference`. Method `activate` hiện tại chỉ gửi 1 reference
([adt_client.py:1788](../../../src/adt_mcp/adt_client.py#L1788)).

**Thêm** `ADTClient.activate_many(system, refs)` với `refs` là list
`(object_type, name, function_group)`; build nhiều `<adtcore:objectReference>` trong
một body và gọi activation một lần. `clone_package` dùng method này ở bước cuối để SAP
tự giải quyết thứ tự kích hoạt giữa các object phụ thuộc.

## 8. Xử lý lỗi & giới hạn đã biết

- **SRVB (service binding)** — **CÓ clone** dù `source_capable=False`. SRVB không
  phải dạng source nhưng `create_object` tạo được khi truyền `service_definition`.
  Xử lý riêng: đọc binding gốc (GET object SRVB) để lấy (a) tên service definition
  được bind, (b) loại/phiên bản binding (ODATA V2/V4 → `binding_version`). Map tên
  service definition qua `rename_map` (vd `ZUI_FUN_MF902` → `ZUI_FUN_MF902_VN`) rồi
  gọi `create_object(SRVB, tên_đích, ..., service_definition=SD_đích,
  binding_version=...)`. Binding sau khi tạo trỏ vào SRVD`_VN`. Lưu ý: SRVB không
  có "source" để ghi, nên bỏ qua bước rewrite/ghi source — chỉ create.
- **Type không tạo được nội dung** (`DTEL`, `DOMA` có `source_capable=False`): v1
  đánh dấu **skip** và liệt kê rõ trong kết quả (chỉ tạo được shell, không copy được
  thuộc tính domain/data element). Ngoài phạm vi v1.
- **Tên đích > 30 ký tự** sau khi thêm suffix: báo `error` cho object đó trong kế
  hoạch, không tạo.
- **Object đích đã tồn tại**: create trả lỗi -> ghi nhận `FAILED`, tiếp tục object
  khác (không dừng cả mẻ). Tổng kết cuối báo số success/skip/failed.
- **Package đích chưa tồn tại**: phát hiện sớm (list/validate) -> trả lỗi rõ ràng,
  yêu cầu tạo package trước.
- **allow_write tắt** trên system đích: trả về thông điệp gate hiện có, không ghi.
- **Session hết hạn**: thông điệp như các tool khác (refresh cookies).

## 9. Kiểm thử

Thêm test trong [tests/](../../../tests/) (theo phong cách `test_write.py`,
`test_server.py`), mock HTTP của `ADTClient`:

1. **Rename map**: list object -> map đúng `_VN`, validate độ dài, loại skip.
2. **Rewrite tham chiếu (ví dụ ZRAP_FUN_MF902)**: source `ZC_FUN_MF902` chứa
   `from ZI_FUN_MF902`; sau rewrite phải thành `from ZI_FUN_MF902_VN`; đồng thời tên
   object ngoài rename_map (vd `I_BUSINESSPARTNER`) **không** bị đổi.
3. **Word boundary**: `ZI_FUN` và `ZI_FUN_MF902` cùng tồn tại -> thay đúng, không
   nuốt tiền tố.
4. **Thứ tự type**: assert thứ tự create theo mục 6.
5. **dry_run=True**: không gọi create/activate, chỉ trả kế hoạch.
6. **Mass activate**: `activate_many` build đúng số reference trong 1 body.
7. **Skip type**: DOMA/DTEL xuất hiện ở plan với trạng thái skip.
8. **SRVB**: binding gốc trỏ SD `ZUI_FUN_MF902` → bản clone gọi create_object với
   `service_definition=ZUI_FUN_MF902_VN`, đúng `binding_version`.
9. **Tool registration**: `clone_package` có trong server và trong `CORE_TOOLS`.

## 10. Các đơn vị thay đổi

| File | Thay đổi |
|---|---|
| `src/adt_mcp/adt_client.py` | + `clone_package(...)`, + `activate_many(...)`, + helper `build_rename_map`, `rewrite_references` (đặt cạnh helper hiện có, thuần hàm để dễ test). |
| `src/adt_mcp/server.py` | + tool `clone_package`, thêm vào `CORE_TOOLS`. |
| `tests/` | + test cho rename/rewrite/order/dry-run/activate/skip/registration. |
| `docs/adt-mcp-overview.md` / `README.md` | cập nhật danh sách tool (nếu có liệt kê). |

## 11. Ví dụ sử dụng

```
# Xem trước (không ghi)
clone_package(source_system="a4h", source_package="ZRAP_FUN_MF902",
              target_package="ZRAP_FUN_MF902_VN")

# Thực thi cùng system
clone_package(source_system="a4h", source_package="ZRAP_FUN_MF902",
              target_package="ZRAP_FUN_MF902_VN", dry_run=False)

# Cross-system DEV -> QAS, giữ suffix khác
clone_package(source_system="dev", source_package="ZRAP_FUN_MF902",
              target_package="ZRAP_FUN_MF902_VN", target_system="qas",
              suffix="_VN", dry_run=False, transport="DEVK900123")
```
