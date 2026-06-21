# Triển khai ADT MCP lên VPS Azure (Windows Server 2022) — Thiết kế & Runbook

**Ngày:** 2026-06-21
**Mục tiêu:** Đưa ADT MCP server lên VPS `win-vps-01` để nhiều người cùng dùng qua Internet, có HTTPS + đăng nhập.

---

## 1. Quyết định đã chốt

| Vấn đề | Lựa chọn |
|---|---|
| Phạm vi truy cập | Internet công cộng + bắt buộc đăng nhập |
| Danh tính SAP | Dùng chung 1 `systems.json` (mọi người chung 1 user SAP) |
| HTTPS / domain | sslip.io (`104-215-184-253.sslip.io`, không cần đăng ký) + Let's Encrypt |
| Kiến trúc bảo mật | Reverse proxy **Caddy** (HTTPS + Basic Auth) đứng trước app |
| Kiểu hướng dẫn | Từng lệnh copy-paste |

## 2. Môi trường thực tế (Azure)

| Hạng mục | Giá trị |
|---|---|
| VM | `win-vps-01` — Windows Server 2022, Standard_B2as_v2 (2 vCPU / 8GB) |
| Resource Group | `RG-WINVPS-SEA` |
| IP công khai | `104.215.184.253` |
| IP nội bộ | `10.0.0.4` |
| NSG | `win-vps-01NSG` — đã mở RDP 3389 + **HTTPS 443 + HTTP 80** ✅ |
| Public IP | `win-vps-01PublicIP` — **Static**, Standard SKU ✅ (không đổi sau reboot) |
| Trạng thái VPS | **Trắng — chưa cài gì** |

## 3. Kiến trúc

```
[Máy người dùng]                          [VM win-vps-01 — 104.215.184.253]
Claude Code / MCP client                  ┌─────────────────────────────────────┐
        │   HTTPS 443                      │  Caddy (Windows Service)  :443/:80   │
        │   Authorization: Basic ...       │   - TLS Let's Encrypt (tự gia hạn)   │
        └─────────────────────────────────▶│   - Basic Auth (user/pass chung)     │
                                           │        │ reverse_proxy nội bộ        │
                                           │        ▼                            │
                                           │  App Python (Windows Service)        │
                                           │  127.0.0.1:8765                      │
                                           │   - /mcp  (MCP streamable-http)     │
                                           │   - /     (web admin)               │
                                           │   - systems.json + cookies/ (secret)│
                                           └─────────────────────────────────────┘
```

- Cổng **8765 không lộ ra Internet**. Chỉ Caddy (cùng máy) gọi `127.0.0.1:8765`.
- Mọi request từ ngoài phải qua **HTTPS + Basic Auth** mới tới được app.
- App Python **không cần sửa code** (đã bind sẵn `127.0.0.1`).

---

## 4. RUNBOOK — làm trên VPS qua RDP

> Mở **Remote Desktop** tới `104.215.184.253:3389`, đăng nhập admin. Mở **PowerShell (Run as Administrator)**. Các lệnh dưới chạy trong PowerShell trừ khi ghi chú khác.

### Bước 1 — Tên miền: KHÔNG cần làm gì (dùng sslip.io)

Tên miền dùng cố định:

```
104-215-184-253.sslip.io
```

sslip.io tự dịch tên này về `104.215.184.253` — không cần đăng ký, không cần thao tác web. Public IP đã là **Static** nên tên này luôn đúng. Chỉ việc dùng nó trong `Caddyfile` (Bước 8) và `.mcp.json` (Bước 13).

### Bước 2 — Cài Python 3.12

```powershell
# Tải Python 3.12 (bản 64-bit) về và cài im lặng, có thêm vào PATH
$py = "$env:TEMP\python-installer.exe"
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $py
Start-Process -Wait -FilePath $py -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1"
# Đóng & mở lại PowerShell để PATH có hiệu lực, rồi kiểm tra:
python --version
pip --version
```

### Bước 3 — Đưa mã nguồn lên VPS

Cách A — cài Git rồi clone (nếu mã ở git remote):
```powershell
winget install --id Git.Git -e --source winget   # nếu winget có sẵn
git clone <URL_REPO> C:\adt-mcp
```
Cách B — không có Git: nén thư mục `adt-mcp` ở máy bạn thành `.zip`, **copy-paste qua cửa sổ RDP** vào `C:\adt-mcp`, rồi giải nén.

Kết quả mong muốn: mã nằm ở `C:\adt-mcp` (chứa `pyproject.toml` / `src/adt_mcp`).

### Bước 4 — Cài phụ thuộc Python

```powershell
cd C:\adt-mcp
pip install -e .
pip install -r requirements.txt        # nếu muốn chạy test
python -m playwright install chromium  # cho chức năng cookie refresh
```

### Bước 5 — Chạy thử app (kiểm tra cục bộ)

```powershell
cd C:\adt-mcp
python -m adt_mcp
# Kỳ vọng log: ADT MCP on http://127.0.0.1:8765 (MCP at /mcp, admin at /)
```
Mở trình duyệt **trên VPS** vào `http://127.0.0.1:8765/` → thấy trang web admin là OK.
Bấm `Ctrl+C` để dừng (lát nữa biến nó thành service).

### Bước 6 — Tải Caddy

```powershell
New-Item -ItemType Directory -Force C:\caddy | Out-Null
# Tải bản Caddy Windows amd64 (1 file exe). Lấy link mới nhất tại https://caddyserver.com/download
Invoke-WebRequest -Uri "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile C:\caddy\caddy.exe
C:\caddy\caddy.exe version
```

### Bước 7 — Tạo mật khẩu Basic Auth (băm bằng Caddy)

```powershell
C:\caddy\caddy.exe hash-password --plaintext "ĐẶT_MẬT_KHẨU_MẠNH_Ở_ĐÂY"
# Copy chuỗi hash kết quả (bắt đầu bằng $2a$...) để dán vào Caddyfile bước sau.
```

### Bước 8 — Tạo Caddyfile

Tạo file `C:\caddy\Caddyfile` với nội dung (thay domain + hash):

```
104-215-184-253.sslip.io {
    encode gzip

    basic_auth {
        team <DÁN_HASH_BƯỚC_7_VÀO_ĐÂY>
    }

    reverse_proxy 127.0.0.1:8765
}
```

> Caddy ≥ 2.8 dùng `basic_auth`. Nếu bản cũ báo lỗi, đổi thành `basicauth`.

Chạy thử Caddy (chưa cần service):
```powershell
cd C:\caddy
.\caddy.exe run --config .\Caddyfile
```
Lần đầu Caddy sẽ tự xin cert Let's Encrypt (cần cổng 80/443 đã mở — xem Bước 9/10). Để dừng: `Ctrl+C`.

### Bước 9 — Mở Windows Firewall trên VPS

```powershell
New-NetFirewallRule -DisplayName "HTTP 80"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "HTTPS 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

### Bước 10 — Mở cổng Azure NSG ✅ ĐÃ XONG

Đã thêm 2 luật inbound vào `win-vps-01NSG`: `Allow-HTTPS-443` (prio 1010, TCP 443) và `Allow-HTTP-80` (prio 1020, TCP 80). Không mở 8765. Bạn không phải làm gì ở bước này.

### Bước 11 — Cài NSSM và biến 2 cái thành Windows Service

```powershell
# Tải NSSM
New-Item -ItemType Directory -Force C:\nssm | Out-Null
Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"
Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath C:\nssm -Force
$nssm = "C:\nssm\nssm-2.24\win64\nssm.exe"

# Service cho app Python
$python = (Get-Command python).Source
& $nssm install adt-mcp $python "-m adt_mcp"
& $nssm set adt-mcp AppDirectory "C:\adt-mcp"
& $nssm set adt-mcp AppStdout "C:\adt-mcp\logs\app.out.log"
& $nssm set adt-mcp AppStderr "C:\adt-mcp\logs\app.err.log"
& $nssm set adt-mcp Start SERVICE_AUTO_START
& $nssm start adt-mcp

# Service cho Caddy
& $nssm install caddy "C:\caddy\caddy.exe" "run --config C:\caddy\Caddyfile"
& $nssm set caddy AppDirectory "C:\caddy"
& $nssm set caddy AppStdout "C:\caddy\caddy.out.log"
& $nssm set caddy AppStderr "C:\caddy\caddy.err.log"
& $nssm set caddy Start SERVICE_AUTO_START
& $nssm start caddy
```

### Bước 12 — Cấu hình hệ thống SAP qua web admin

1. **Trên VPS** (qua RDP) mở trình duyệt: `https://104-215-184-253.sslip.io/` → nhập Basic Auth (`team` + mật khẩu).
2. Thêm các hệ thống SAP (URL, client, ngôn ngữ, auth).
3. Với auth kiểu `cookie` chế độ `browser`/`cdp`: làm bước login **trong RDP** (vì nó bật trình duyệt thật).

### Bước 13 — Phát cấu hình cho mọi người

Mỗi người dán đoạn sau vào `.mcp.json` của Claude Code (TÔI sẽ tạo sẵn chuỗi base64):

```json
{
  "mcpServers": {
    "sap-adt": {
      "type": "http",
      "url": "https://104-215-184-253.sslip.io/mcp",
      "headers": { "Authorization": "Basic <BASE64(team:mật_khẩu)>" }
    }
  }
}
```

---

## 5. Kiểm thử nghiệm thu

- **Trên VPS:** `curl http://127.0.0.1:8765/` → app sống.
- **Qua Caddy không auth:** `curl.exe -i https://104-215-184-253.sslip.io/mcp` → trả **401 Unauthorized**.
- **Qua Caddy có auth:** `curl.exe -i -u team:mật_khẩu https://104-215-184-253.sslip.io/mcp` → MCP phản hồi (không còn 401).
- **Từ máy khác:** thêm `.mcp.json`, khởi động Claude Code → thấy tool `sap-adt` hoạt động.

## 6. Vận hành

- **Reboot:** cả 2 service tự bật lại (`SERVICE_AUTO_START`).
- **Cập nhật code:** `cd C:\adt-mcp; git pull; Restart-Service adt-mcp`.
- **Xem log:** `C:\adt-mcp\logs\*.log`, `C:\caddy\caddy.*.log`.
- **Đổi mật khẩu chung:** chạy lại Bước 7, sửa `Caddyfile`, `Restart-Service caddy`, phát lại `.mcp.json`.

## 7. Bảo mật & rủi ro

- Cổng 8765 không lộ ra ngoài (app bind localhost).
- HTTPS bảo vệ mật khẩu + cookie SAP khi truyền.
- Secrets (`systems.json`, `cookies/`, mật khẩu Caddy) **chỉ ở VPS, không commit git**.
- **Hạn chế:** dùng chung 1 danh tính SAP → không truy vết được ai thao tác gì (đã chấp nhận).
- **Tăng cường về sau (tùy chọn):** giới hạn `source` cổng 443 theo dải IP công ty trên NSG; thêm fail2ban-style rate limit ở Caddy; chuyển sang Bearer token riêng cho `/mcp`.

## 8. Phân công

- **Claude (từ máy này):** ✅ mở cổng NSG 80/443; ✅ xác nhận IP tĩnh. Còn lại: sinh chuỗi base64 cho `.mcp.json` sau khi bạn chốt mật khẩu.
- **Bạn (qua RDP vào VPS):** chạy các lệnh Bước 2–9, 11–13 (Bước 1 và 10 không phải làm).
