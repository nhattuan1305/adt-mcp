# adt-mcp — Tổng hợp kiến thức
MCP server (Python) làm cầu nối giữa AI agent và hệ thống SAP qua giao thức
**ADT** (ABAP Development Tools): cho AI **đọc, hiểu, sửa, kiểm thử và profiling**
code ABAP/RAP trực tiếp trên S/4HANA Public Cloud — có cơ chế an toàn ghi, tối ưu
token, và đã được kiểm chứng trực tiếp trên hệ thống thật.

---

## 1. Elevator pitch (30 giây)

> "adt-mcp là một MCP server bắc cầu giữa AI và SAP qua ADT. Nó biến năng lực của
> Eclipse ADT (đọc/sửa class, CDS, RAP behavior, chạy ABAP Unit, xem dữ liệu,
> profiling hiệu năng) thành các **tool MCP** để AI dùng được — an toàn, tiết kiệm
> token, và đã chạy thật trên S/4HANA Public Cloud."

## 2. Bối cảnh & vấn đề

- Lập trình **ABAP RAP trên SAP Public Cloud** chủ yếu qua Eclipse ADT — thao tác
  tay, AI khó tham gia.
- ADT là REST/HTTP nhưng **không có tài liệu mở**: nhiều endpoint kén `Accept`
  header, có flow **stateful** (lock + CSRF), auth qua **SAML/IAS cookie**.
- Mục tiêu: đưa toàn bộ năng lực đó thành **tool MCP** dùng được, an toàn, tiết
  kiệm token.

## 3. Kiến trúc

```
AI agent ──MCP(streamable-http)──▶ FastMCP server ──HTTP/ADT──▶ SAP (S/4 Cloud)
                                     │
        ┌────────────────────────────┼───────────────────────────┐
     registry.py                 adt_client.py               cookie_refresh.py
   (multi-system,              (toàn bộ logic ADT:          (login SAML/IAS qua
    systems.json)               parse XML, CSRF, lock,        Playwright headless
                                stateful write, parsers)      + persistent profile)
                                     │
                                server.py ── 29 tool MCP + web admin (Starlette)
```

- **Tách lớp sạch**: registry (config) / adt_client (HTTP thuần, dễ test) /
  server (wiring MCP + web admin) / cookie_refresh (auth).
- **Một tiến trình** phục vụ cả `/mcp` (cho AI) và `/` (web admin cấu hình hệ thống).
- Stack: **Python · FastMCP · httpx · Starlette · Playwright**.

## 4. Bộ tool (29 tool — trình bày theo nhóm)

| Nhóm | Tool tiêu biểu | Giá trị |
|---|---|---|
| Đọc / điều hướng | `get_source`, `list_package`, `search_objects`, `grep_package` | duyệt repository |
| **Hiểu (intelligence)** | **`get_context`**, `find_references`, `cds_dependencies`, `api_release_state` | dựng "bức tranh" 1 đối tượng RAP trong 1 call |
| Lịch sử | `get_revisions`, `compare_source` | diff phiên bản |
| Chất lượng / runtime | `syntax_check`, **`run_unit_tests`**, **`data_preview`** | kiểm thử & xem dữ liệu |
| **Hiệu năng** | **`trace_start` / `trace_list` / `trace_analyze`** | profiling vì sao chậm (CPU + DB) |
| **Lỗi runtime** | **`list_dumps` / `get_dump`** | đọc short dump ST22 để AI phân tích lỗi |
| Ghi (có gate) | `update_source`, `update_class_include`, `create_object`, `activate`, **`clone_package`** | sửa & activate, scaffold RAP, clone package (+suffix `_VN`, rewrite tham chiếu) |
| Phiên | `refresh_cookies_for` | tự làm mới cookie |

## 5. Điểm kỹ thuật "ăn điểm"

### a) Reverse-engineer giao thức ADT (không tài liệu)
- ADT bắt **`Accept` header vendor-type rất cụ thể** — sai là HTTP 406. Kỹ thuật:
  gửi `Accept` sai có chủ đích để server **tự khai báo** type đúng (vd
  `application/vnd.sap.adt.datapreview.table.v1+xml`,
  `…abapunit.testruns.result.v2+xml`). → phương pháp "đọc lỗi để học contract".
- Ghi là flow **stateful**:
  `CSRF token → LOCK → PUT (kèm lockHandle) → UNLOCK → activate`.
  Có **cache CSRF token + retry khi 403**, dùng **cookie jar** để tôn trọng
  session-id mà server xoay giữa chừng, và **cảnh báo "object có thể còn bị khóa"**
  khi PUT lỗi mà unlock cũng thất bại.

### b) `get_context` — tối ưu cho RAP (killer feature)
- Một call trên BDEF tự kéo về: CDS behavior-for (+ dependencies) và behavior pool
  class — **nén lại** (bỏ annotation / phần implementation) để **tiết kiệm token**
  mà vẫn đủ ngữ cảnh. Giúp AI hiểu cả một Business Object trong một lượt.

### c) An toàn ghi (safe by design)
- Ghi **tắt mặc định**; muốn bật phải có `allow_write` **và** package khớp
  `write_packages` (mặc định `Z*`, `$TMP`).
- Gate đọc **package thật** của object (không tin tham số đầu vào).
- **Không hỗ trợ delete** — cố ý.

### d) Token economy (rất hợp câu hỏi "tối ưu chi phí LLM")
- Schema tool gửi **mỗi turn** ⇒ là chi phí thường trực → có chế độ
  `ADT_MCP_TOOLS=core` (16 tool ~2.7k tokens) vs `full` (29 tool ~4.9k); mô tả tool
  viết cực ngắn.
- **So sánh thật** với `vsp` (một ADT-MCP viết bằng Go), cùng lấy 1 class Z trên hệ
  thống thật:

| Hạng mục | adt-mcp | vsp |
|---|---|---|
| Lấy 1 object (payload) | ~772 tokens (CRLF) | ~747 tokens (LF) — *nội dung ABAP giống hệt* |
| Schema/turn — hyperfocused | — | 1 tool, ~411 tokens |
| Schema/turn — core | 16 tool, ~2.7k | — |
| Schema/turn — full / focused | 29 tool, **~4.9k** | 101 tool, **~16.8k** |
| Schema/turn — expert | — | 145 tool, ~24k |

→ Lấy object thì **ngang nhau** (khác biệt chỉ do CRLF vs LF). Chi phí thật nằm ở
**schema lặp lại mỗi turn**: adt-mcp full nhẹ hơn vsp focused **~3.4×**, core nhẹ
hơn **~6×**.

### e) Auth SAML/IAS thực dụng
- 3 cách lấy cookie: **browser login** (persistent profile nhớ SSO), **headless**
  với credential đã lưu, hoặc **attach Chrome qua CDP**.
- Phát hiện "trang SAML trả về HTTP 200" để báo **session hết hạn** rõ ràng thay vì
  lỗi mơ hồ.

### f) ABAP Profiler (phần khó nhất)
- **ST05 SQL trace không đọc được kết quả qua ADT** trong Public Cloud (endpoint chỉ
  redirect sang Fiori app) → **pivot** sang **ABAP Profiler** (`abaptraces`): tạo
  parameters → tạo request → chạy workload → đọc **hitlist** + **DB accesses** (gồm
  cả phân tích SQL — bao luôn nhu cầu mà ST05 định làm).
- Tự dò contract bằng **PoC trên hệ thống thật** + đối chiếu thư viện open-source
  `abap-adt-api`.

## 6. Quy trình kỹ thuật (cách làm việc)

- **TDD**: viết test trước (httpx `MockTransport`), đỏ → code → xanh; hiện **92 test
  pass**.
- **Verify trên hệ thống thật**: mọi tool mới đều chạy đối chiếu trên S/4 Public
  Cloud thật — phát hiện được thứ unit test không thấy (Accept 406, CRLF, ST05
  redirect, projection view trả 500).
- **Trung thực về phạm vi**: phân biệt rõ "đã verify trên hệ thống thật" vs "mới chỉ
  unit-test".

## 7. Con số chốt hạ

- **29 tool** (16 core) · ~1.900 dòng `adt_client.py` · **92 test pass** ·
  schema **4.9k / 2.7k token** · multi-system · hỗ trợ RAP / CDS / BDEF / SRVB.

## 8. "Nếu có thêm thời gian" (câu hỏi cuối thường gặp)

- Normalize **CRLF→LF** để giảm ~3% token mỗi lần đọc source.
- Thêm **`run_console`** (ABAP console runner) làm vòng lặp "print-debug" cho AI.
- **ATC checks**, transport management, publish service binding, **OS-keyring** cho
  password (thay vì plaintext).

## 9. Gợi ý kể chuyện (STAR) cho 1 câu hỏi

- **Situation**: Cần cho AI sửa RAP trên SAP Cloud, nhưng ADT không tài liệu, kén
  header, có flow stateful.
- **Task**: Xây MCP server an toàn, tiết kiệm token.
- **Action**: Tách lớp rõ ràng; reverse-engineer contract bằng cách "đọc lỗi
  server"; TDD + verify trên hệ thống thật; thêm `get_context`/profiler tối ưu cho
  RAP; gate ghi nhiều lớp.
- **Result**: 29 tool chạy thật trên S/4 Cloud, 92 test, schema nhẹ hơn ~3–6× so với
  giải pháp Go tương đương.

---

## Phụ lục — thuật ngữ nhanh

- **ADT**: ABAP Development Tools — API HTTP của SAP cho công cụ phát triển (Eclipse
  dùng chính nó).
- **RAP**: ABAP RESTful Application Programming model — cách viết business object +
  service trên ABAP Cloud.
- **CDS / DDLS**: Core Data Services — view khai báo trên DB (đối tượng `DDLS`).
- **BDEF / behavior pool**: định nghĩa hành vi RAP + class hiện thực hành vi.
- **SRVD / SRVB**: service definition / service binding (xuất OData).
- **MCP**: Model Context Protocol — chuẩn để AI agent gọi tool/khám phá tool.
- **CSRF / stateful session**: cơ chế bảo vệ ghi của ADT (token + lock handle).
