# deploy/ — chạy máy chủ Lữ Trình bằng Docker Compose

Theo thiết kế trang 06 (§4–§9; D-18 A Docker Compose, D-19 A Caddy, D-21 A restic).

| Tệp | Việc |
| --- | --- |
| `Dockerfile` | Image `app` (Python 3.12 + uv, ffmpeg, `spec/`, `admin/dist`; uid 10001) và `caddy` (Caddyfile + `admin/dist`; uid 10002). Build từ gốc repo. |
| `compose.yaml` | `app` (API, :8000 chỉ trong mạng Docker), `worker` (ảnh, video, chặng), `caddy` (cổng 80/443). Profile `tunnel` (cloudflared), `backup` (restic). |
| `Caddyfile` | Ba chế độ chọn bằng `.env`: tên miền + HTTPS tự động, LAN http, sau Cloudflare Tunnel. Media qua `X-Accel-Redirect` (Range do Caddy lo), thân yêu cầu ≤ 10 MB. |
| `.env.example` | Chép thành `.env` (quyền 600, không vào git). |
| `bootstrap.sh` | Lần đầu: thư mục dữ liệu, build, migration, tài khoản quản trị, `up -d`. |
| `backup.sh` | Sao lưu đêm (DB + restic ra ngoài host), `--now` (chỉ DB), `--restore`. |
| `systemd/` | Timer chạy `backup.sh` mỗi đêm. |

Dữ liệu nằm ở một thư mục trên host, mặc định `/var/lib/lutrinh` (`db/`, `media/`, `uploads/`,
`backups/`, `tmp/`), chủ là uid 10001. Container chạy không phải root, hệ thống tệp chỉ đọc trừ
thư mục này.

## 1. Cài Docker (Debian 12 / Ubuntu 22.04, 24.04)

```sh
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
. /etc/os-release   # ID=debian hoặc ubuntu
sudo curl -fsSL https://download.docker.com/linux/$ID/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"   # đăng xuất / vào lại
docker compose version            # cần ≥ 2.24
```

Đồng hồ phải đúng (TOTP): `timedatectl` phải báo `System clock synchronized: yes`.
Tường lửa: chỉ mở 22 (SSH bằng khoá), 80, 443 (chế độ 1); chế độ 3 không cần mở 80/443.

## 2. Lấy mã nguồn

```sh
sudo mkdir -p /opt/lutrinh && sudo chown "$USER" /opt/lutrinh
git clone <địa-chỉ-repo> /opt/lutrinh      # hoặc chép bản phát hành (rsync/scp) vào /opt/lutrinh
cd /opt/lutrinh
cp deploy/.env.example deploy/.env && chmod 600 deploy/.env
```

## 3. Chọn chế độ trong `deploy/.env`

1. **Tên miền + HTTPS tự động** (host có IP công khai, mở được 80/443; bản ghi A/AAAA của tên
   miền trỏ về host): `LUTRINH_SITE=lutrinh.example.com`, `LUTRINH_HTTP_PORT=80`,
   `LUTRINH_HTTPS_PORT=443`. Caddy tự xin và gia hạn chứng chỉ Let's Encrypt.
2. **LAN, http trên một cổng** (máy trong mạng nhà/Proxmox, chưa có tên miền):
   `LUTRINH_SITE=:80`, `LUTRINH_HTTP_PORT=8080`. App gọi `http://<ip-máy>:8080/api/v1/...`.
   **Web quản trị:** cookie đăng nhập là `__Host-…; Secure`, trình duyệt chỉ nhận nó qua
   https hoặc qua `http://localhost`. Vì vậy ở chế độ này mở web quản trị qua đường hầm SSH:
   ```sh
   ssh -L 8080:localhost:8080 <user>@<ip-máy>     # rồi mở http://localhost:8080/admin/
   ```
   (Mở thẳng `http://<ip-máy>:8080/admin/` sẽ không đăng nhập được; đó là cố ý, không nới cookie.)
3. **Cloudflare Tunnel** (không có IP công khai): tạo tunnel trong Cloudflare Zero Trust, thêm
   public hostname với service `http://caddy:80`, chép token vào `.env`:
   `LUTRINH_SITE=:80`, `LUTRINH_BIND=127.0.0.1`, `LUTRINH_TRUSTED_PROXIES=private_ranges`,
   `LUTRINH_CLIENT_IP_HEADERS=CF-Connecting-IP`, `CLOUDFLARE_TUNNEL_TOKEN=…`.
   Chạy mọi lệnh `docker compose` với `--profile tunnel` (hoặc đặt `COMPOSE_PROFILES=tunnel`
   trong `.env`).

**Sau một reverse proxy có sẵn** (chế độ 2 sau nginx-proxy-manager + Cloudflare, như VM 106
`luhanh.vuongchison.com`): proxy giữ 80/443 nên đặt `LUTRINH_HTTP_PORT=8090` và
`LUTRINH_HTTPS_PORT` là một cổng trống khác (compose luôn mở cổng này, mặc định 443 sẽ đụng
proxy). `LUTRINH_TRUSTED_PROXIES=private_ranges`; tên miền đi qua Cloudflare thì
`LUTRINH_CLIENT_IP_HEADERS=CF-Connecting-IP` (`X-Real-IP` của NPM là IP Cloudflare,
`X-Forwarded-For` lấy giá trị trái nhất, client giả được). Web quản trị đăng nhập được qua
https của proxy. Kiểm tra: tra một mã rồi xem `ip_events.ip` là IP thật của máy mình.

`LUTRINH_DATA_PATH` là thư mục dữ liệu (mặc định `/var/lib/lutrinh`). Cấu hình máy chủ thêm
(`LUTRINH_MAINTENANCE`, `LUTRINH_MIN_APP_ANDROID`, …; xem `server/lutrinh/config.py`) đặt trong
`deploy/app.env` (tuỳ chọn).

## 4. Chạy lần đầu, tạo tài khoản quản trị

```sh
deploy/bootstrap.sh
```

Lệnh tạo thư mục dữ liệu (chủ uid 10001, dùng `sudo` khi cần), build image (lần đầu vài phút),
chạy migration, hỏi mật khẩu quản trị hai lần (≥ 14 ký tự) rồi in **mã TOTP** (quét bằng app
Authenticator) và **10 mã dự phòng** (in ra giấy; không lưu ở đâu khác), cuối cùng `up -d`.

Kiểm tra:

```sh
curl -fsS http://localhost:8080/api/v1/meta     # chế độ 2; chế độ 1: https://<tên-miền>/api/v1/meta
docker compose -f deploy/compose.yaml ps        # app (healthy), worker, caddy (healthy)
```

Thử nhanh với lộ trình mẫu (in ra `Mã: XXXX-XXXX`, mỗi lần chạy thêm một lộ trình):

```sh
docker compose -f deploy/compose.yaml exec app lutrinh seed-sample
```

Quên mật khẩu / mất máy TOTP (không có "quên mật khẩu" qua thư):

```sh
docker compose -f deploy/compose.yaml run --rm app lutrinh admin reset
```

## 5. Sao lưu và khôi phục (D-21)

Đặt `RESTIC_REPOSITORY` và `RESTIC_PASSWORD` trong `.env` (giữ một bản mật khẩu ở nơi khác:
mất nó là không đọc được bản sao lưu). Kho có thể là S3/B2 (`s3:…`, `b2:…` + khoá), `sftp:…`,
hoặc `/repo-local` = thư mục `RESTIC_LOCAL_DIR` trên một ổ khác của host.

```sh
deploy/backup.sh            # DB → backups/db-<ngày-giờ>.sqlite (giữ 7), restic backup backups/ + media/,
                            # restic forget --keep-daily 30 --keep-monthly 6 --prune
deploy/backup.sh --now      # chỉ chép DB (trước khi cập nhật)
deploy/backup.sh --restore [SNAPSHOT] [--yes]   # mặc định bản mới nhất
```

`--restore` dừng `caddy`, `worker`, `app`, khôi phục `backups/` và `media/` vào thư mục dữ liệu,
lấy bản `backups/db-*.sqlite` mới nhất làm `db/lutrinh.sqlite`, rồi `up -d`. Trên một host mới:
làm bước 1–3, `deploy/bootstrap.sh` (tạo tạm một tài khoản, sẽ bị bản khôi phục thay), rồi
`deploy/backup.sh --restore`.

Chạy mỗi đêm bằng systemd (đường dẫn trong unit là `/opt/lutrinh`; mã ở chỗ khác thì sửa
`ExecStart` khi chép, ví dụ `sed 's#/opt/lutrinh/#/opt/lutrinh-server/#'` trên VM 106):

```sh
sudo cp deploy/systemd/lutrinh-backup.* /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lutrinh-backup.timer
systemctl list-timers lutrinh-backup.timer
```

(Hoặc cron: `30 2 * * * /opt/lutrinh/deploy/backup.sh >> /var/log/lutrinh-backup.log 2>&1`.)
Ba tháng một lần thử khôi phục lên một máy/VM tạm và tra một mã (trang 06 §9).

## 6. Cập nhật và quay lại

```sh
cd /opt/lutrinh && git pull
deploy/backup.sh --now
LUTRINH_TAG=$(date +%F) docker compose -f deploy/compose.yaml build   # giữ image cũ để quay lại
LUTRINH_TAG=$(date +%F) docker compose -f deploy/compose.yaml up -d   # app tự chạy alembic upgrade head
curl -fsS http://localhost:8080/api/v1/meta
```

Đặt `LUTRINH_TAG` mới vào `.env` để các lệnh sau dùng nó. Lỗi thì đặt lại tag cũ, `up -d`, và
khôi phục DB vừa chép (`backups/db-…sqlite` → `db/lutrinh.sqlite` khi stack đã dừng).

## 7. Nhật ký

`docker compose -f deploy/compose.yaml logs -f app worker caddy`. Docker giữ tối đa 5 × 20 MB mỗi
dịch vụ. Caddy không ghi nhật ký truy cập (IP đã nằm trong DB, xoá sau 14 ngày).

## Ghi chú

- Proxmox VM: cho VM ≥ 2 vCPU, ≥ 2 GB RAM, ≥ 40 GB đĩa (trang 06 §6).
- `deploy/*.sh` đọc `deploy/.env` (hoặc `LUTRINH_ENV_FILE`); có `COMPOSE_FILE` thì dùng danh
  sách tệp compose đó (thêm tệp override riêng của host).
- macOS + Docker Desktop: restic gặp `input/output error` khi đọc tệp trong thư mục chia sẻ từ
  macOS. Trên máy Mac chỉ thử được sao lưu khi dữ liệu nằm trong một named volume (tệp override).
  Host Linux không bị.
