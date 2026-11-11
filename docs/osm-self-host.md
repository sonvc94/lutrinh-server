# Tự host dịch vụ OpenStreetMap (bản trích Geofabrik Việt Nam) trên Proxmox: có khả thi không?

Ngày khảo sát: 2026-11-11. Câu hỏi của thuyền trưởng: "nghiên cứu openstreetmap + geofabrik
Vietnam openstreetmap extract, có khả thi cài đặt trên Proxmox không?"

**Trả lời ngắn: khả thi có điều kiện.** Bản trích Việt Nam nhỏ (317 MB). Trên máy Mac, dựng bản đồ
vector mất 2 phút 33 giây, đồ thị Valhalla mất 2 phút 43 giây, chỉ mục Photon mất 40 giây. Khi đã
dựng xong, cả ba chạy cùng nhau cần khoảng 2 GB đĩa và 1–2 GiB RAM. Điều kiện nằm ở máy Proxmox,
không nằm ở dữ liệu:

- máy có 15,4 GiB RAM và đã cấp 14 GiB cho các CT đang chạy;
- máy chỉ có một ổ NVMe 500 GB;
- thin pool đang cấp vượt dung lượng thật.

Vì vậy nên dựng dữ liệu ở nơi khác (máy Mac hoặc chạy ban đêm với ít luồng), còn Proxmox chỉ
phục vụ. Thuyền trưởng cần quyết định đặt dịch vụ vào CT mới hay vào CT 106 (mục 6).

Ký hiệu số liệu:

- **[Đo]**: tự đo trong lần khảo sát này (trên máy Mac hoặc trên máy chủ, đã ghi lệnh).
- **[Trích]**: lấy từ tài liệu (có nguồn ở mục 9).
- **[Ước]**: tự ước lượng, chưa đo và không có nguồn trực tiếp.

## 1. Bản trích Geofabrik Việt Nam là gì

| Mục | Giá trị | Loại |
| --- | --- | --- |
| Tệp | `https://download.geofabrik.de/asia/vietnam-latest.osm.pbf` | |
| Kích thước | 332 453 587 byte = **317 MiB** (`Content-Length`, khớp `md5` = `403c67e51cb9a548e215f52a08a821ac`) | [Đo] |
| Ngày dữ liệu | Trang Geofabrik ghi "contains all OSM data up to 2026-11-09T21:22:17Z"; tiêu đề `Last-Modified: Tue, 10 Nov 2026 08:40:38 GMT` | [Đo] |
| Tải về | 33 giây từ mạng này (`/usr/bin/time -p curl …` → `real 33.05`) | [Đo] |
| Cập nhật | Mỗi ngày một lần, "around 21:00 CET". Có bản diff hằng ngày ở `https://download.geofabrik.de/asia/vietnam-updates/` (`state.txt` ngày 2026-11-11: `sequenceNumber=4966`, `timestamp=2026-11-10T21:21:39Z`). Diff giữ 100 ngày. | [Trích] + [Đo] |
| Giấy phép | Dữ liệu OSM theo **ODbL 1.0**. Phải ghi "© OpenStreetMap contributors". Nếu phát hành một cơ sở dữ liệu đã sửa (ví dụ trộn thêm nguồn khác) thì cơ sở dữ liệu đó cũng theo ODbL. Ảnh bản đồ (tile) là "produced work": chỉ cần ghi công. Bản công khai của Geofabrik đã bỏ `user`, `uid`, `changeset`. | [Trích] |
| Vùng phủ | Đa giác `vietnam.poly`: một vòng, 120 điểm, khung lon 102,10–114,64, lat 7,38–23,40. **Không gồm quần đảo Hoàng Sa** (Phú Lâm, đảo Hoàng Sa, Tri Tôn đều nằm ngoài) và **không gồm phần lớn Trường Sa** (Trường Sa Lớn, Sinh Tồn, Ba Bình nằm ngoài; Song Tử Tây, Đá Tây nằm trong). | [Đo] (kiểm tra điểm trong đa giác bằng Python) |

Lữ Trình đã dùng tệp này để dựng gazetteer offline (`polarsteps-clone-native`
`tools/gazetteer/build_gazetteer.py`). Lữ Trình không dùng vào mục đích thương mại, nhưng ODbL
không phân biệt thương mại hay không: chỉ cần ghi công và tuân thủ điều khoản share-alike.

## 2. Hôm nay Lữ Trình dùng gì (đã kiểm tra trong mã)

| Nhu cầu | Đang dùng | Nơi cấu hình |
| --- | --- | --- |
| Bản đồ nền | OpenFreeMap, kiểu `positron` (`https://tiles.openfreemap.org/styles/positron`) và ảnh vệ tinh Esri World Imagery | app `map/basemap/OpenFreeMap.kt`, `EsriWorldImagery.kt` |
| Chỉ đường | Valhalla FOSSGIS `valhalla1.openstreetmap.de`; dự phòng OSRM car `routing.openstreetmap.de/routed-car` | app `routing/Routers.kt`; server `lutrinh/config.py` (`valhalla_url`, `osrm_car_url`); costing `motor_scooter`, `auto`, `bus`, `pedestrian` (`adapters/routing/valhalla.py`) |
| Tìm địa danh | Gazetteer offline dựng từ tệp pbf Geofabrik | app `tools/gazetteer/` |
| Hoàng Sa / Trường Sa (R30) | Ẩn nhãn hành chính Trung Quốc và tự vẽ "Quần đảo Hoàng Sa", "Quần đảo Trường Sa" | app `map/SovereigntyLabels.kt`; admin `src/map/sovereignty.ts` |

Máy chủ FOSSGIS giới hạn "tối đa một yêu cầu mỗi giây", không cam kết luôn sẵn sàng, và không
dành cho trang có lưu lượng lớn [S12]. Vì vậy worker có `Throttle` ≥ 1 giây. Đây là lý do chính để
tự host chỉ đường.

## 3. Đo trên máy Mac (một lần thử cho mỗi dịch vụ)

Máy đo: Mac Apple Silicon, 10 nhân, 16 GB RAM. Docker Desktop được cấp 10 CPU và 7,65 GiB RAM.
Mọi dữ liệu nằm trong `/Volumes/wdblack/tmp/research-osm-selfhost/`.

| Dịch vụ | Lệnh (rút gọn) | Thời gian | Kết quả | RAM | Loại |
| --- | --- | --- | --- | --- | --- |
| **Planetiler** (OpenMapTiles → PMTiles) | `docker run -e JAVA_TOOL_OPTIONS=-Xmx4g ghcr.io/onthegomap/planetiler:latest --area=vietnam --osm-path=…/vietnam.osm.pbf --download --output=/data/vietnam.pmtiles` | `real 154.59` giây. Planetiler: `overall 2m33s cpu:10m38s`; tải nguồn phụ 38 s; `osm_pass1` 6 s; `osm_pass2` 27 s; `archive` 49 s | `vietnam.pmtiles` **320 MB** (319 315 415 byte), z0–14, 415 758 tile. Nguồn phụ (water polygons 933 MB, Natural Earth 433 MB, lake centerline 81 MB): 1,7 GB, chỉ cần khi dựng | heap Java cao nhất ~1,7 GB / 4,2 GB | [Đo] |
| **Valhalla** (đồ thị chỉ đường) | `docker run -e serve_tiles=False -e build_elevation=False -e build_admins=True -e build_time_zones=True -e server_threads=8 ghcr.io/valhalla/valhalla-scripted:latest` (Valhalla 3.9.1) | `real 162.93` giây | `valhalla_tiles/` 1,2 GB và `valhalla_tiles.tar` 1,1 GB (bản tar dùng để phục vụ; giữ một trong hai), `timezones.sqlite` 128 MB, `admins.sqlite` 12 MB | cao nhất **5,0 GiB** khi dựng (`docker stats`, 8 luồng). Khi phục vụ: 107 MiB lúc vừa khởi động | [Đo] |
| Valhalla: thử phục vụ | `POST /route` Đà Lạt (11,9404, 108,4583) → Nha Trang (12,2388, 109,1967) | 0,074 s (`motor_scooter`); 0,025 s (`auto`) | `motor_scooter` 136,4 km, 194 phút; `auto` 192,8 km, 174 phút | | [Đo] |
| **Photon** 1.3.0 (tìm địa điểm, gõ đến đâu gợi ý đến đó) | `zstd -d photon-dump-vietnam-1.0-latest.jsonl.zst \| docker run -i eclipse-temurin:21-jre java -jar photon.jar import -import-file - -languages vi,en` | `real 39.58` giây (Photon ghi "Finished import of 470736 photon documents. (Total processing time: 34s)") | chỉ mục **182 MB**. Bản dump Việt Nam 71,4 MB, ngày dữ liệu 2026-11-08 | khi phục vụ: **488 MiB** (`-Xmx1g`) | [Đo] |
| Photon: thử tìm | `GET /api?q=…` | | "ho hoan kiem" → Hồ Hoàn Kiếm; "cho da lat" → Chợ đêm Da Lat, Chợ Đà Lạt mới (Lâm Đồng); "truong sa" → Trường Sa, Đảo Trường Sa (Khánh Hòa) | | [Đo] |
| **OSRM** car (MLD) | `osrm-extract -p /opt/car.lua` → `osrm-partition` → `osrm-customize` (`ghcr.io/project-osrm/osrm-backend:latest`) | **thất bại** sau `real 86.14` giây, ở bước `osrm-extract` | `exit 137` (bị kill do hết bộ nhớ trong giới hạn 7,65 GiB của Docker). Theo luật một lần thử, không chạy lại | > 7,6 GiB khi extract với 10 nhân | [Đo] |
| Nominatim, Pelias, Overpass | không chạy | | Lý do: bản dump Photon đã được dựng từ Nominatim, và đã đủ để trả lời câu hỏi tìm kiếm. Nominatim cần PostgreSQL, nặng hơn nhiều; Pelias cần ít nhất 8 GB RAM, vượt khả năng hiện có (mục 4). Overpass không cần cho app | | |

Máy Proxmox dùng i5-8500T (6 nhân, 2,1 GHz, turbo ~3,2 GHz đo được qua API), chậm hơn máy Mac.
**[Ước]** Thời gian dựng trên máy đó sẽ gấp khoảng 2–4 lần: Planetiler 5–10 phút, Valhalla 6–12
phút. Muốn biết chính xác thì phải chạy thử trên máy đó.

## 4. Bảng từng dịch vụ

| Dịch vụ | Vai trò cho Lữ Trình | Docker image | Thời gian import (VN) | Đĩa (VN) | RAM | CPU | Cập nhật | Công bảo trì | Giấy phép phần mềm | Kết luận |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Bản đồ vector**: Planetiler → PMTiles, phục vụ bằng Martin (hoặc Caddy file tĩnh / TileServer GL) | Thay OpenFreeMap. Lược đồ OpenMapTiles giống hệt lược đồ OpenFreeMap đang dùng, nên kiểu `positron` và bộ lọc R30 hiện có vẫn dùng được | `ghcr.io/onthegomap/planetiler` (dựng); `ghcr.io/maplibre/martin` (phục vụ: PMTiles, MBTiles, PostGIS; có cả style, sprite, font) | 2 phút 33 giây [Đo] | 320 MB khi chạy; khi dựng cần 1,7 GB nguồn phụ và thư mục tạm [Đo]. Tài liệu: "1GB … plus 5-10x the size of the .osm.pbf" [Trích] | dựng: heap 4 GB là đủ (dùng 1,7 GB) [Đo]; phục vụ: < 100 MB [Ước] | dựng: trung bình 4,2 nhân [Đo]; phục vụ: rất nhẹ | dựng lại toàn bộ (vài phút) theo lịch tuần, đổi tệp nguyên khối | thấp | Planetiler Apache-2.0; Martin Apache-2.0 (theo GitHub); ghi công "© OpenMapTiles" (CC-BY 4.0) và "© OpenStreetMap contributors" | **khả thi** |
| **Valhalla** | Worker `jobs/legs.py` tính chặng đường, và app chỉ đường. Bỏ được giới hạn 1 yêu cầu/giây của FOSSGIS; dùng được `motor_scooter` như hiện nay | `ghcr.io/valhalla/valhalla-scripted:latest` (cổng 8002) | 2 phút 43 giây [Đo] | ~1,5 GB (tar 1,1 GB + timezones + admins) [Đo] | dựng: 5,0 GiB với 8 luồng [Đo]; giảm `server_threads` thì giảm RAM [Trích]. Phục vụ: 0,1–1 GiB [Đo lúc khởi động; mức cao hơn là Ước] | dựng: nhiều nhân; phục vụ: nhẹ | không cập nhật từng phần: dựng lại từ pbf mới (`force_rebuild=True`) hoặc dựng ở nơi khác rồi chép `valhalla_tiles.tar` vào với `use_tiles_ignore_pbf=True` [Trích] | thấp | MIT | **khả thi** |
| **OSRM** (thay thế) | Dự phòng cho xe hơi; hiện là dự phòng của FOSSGIS. Không có costing xe máy riêng như Valhalla | `ghcr.io/project-osrm/osrm-backend` (cổng 5000) | lần thử bị kill do hết RAM sau 86 giây [Đo] | ước 1–2 GB mỗi profile [Ước] | extract > 7,6 GiB với 10 nhân [Đo] | | dựng lại cho từng profile | trung bình (mỗi profile một bộ dữ liệu) | BSD-2-Clause | **khả thi có điều kiện**: phải dựng trên máy nhiều RAM hơn (hoặc giảm luồng, chưa thử). Không cần nếu đã có Valhalla |
| **Photon** | Ô tìm kiếm trực tuyến, gõ đến đâu gợi ý đến đó (Nominatim cấm dùng máy chủ công cộng cho việc này); tìm ngược tọa độ. Bổ sung cho gazetteer offline, không thay nó | không có image chính thức; chạy `photon.jar` trong `eclipse-temurin:21-jre` | 34–40 giây từ bản dump [Đo] | 182 MB [Đo] | phục vụ 0,5 GiB [Đo] | nhẹ | tải bản dump mới của GraphHopper (bản 1.0 cho Việt Nam: 71,4 MB, ngày 2026-11-09), dựng thư mục mới rồi tráo; "never unpack the new database over the old one" [Trích] | thấp | Apache-2.0; dữ liệu ODbL | **khả thi**. Cần nhớ: Photon không hiểu từ chỉ loại địa điểm tiếng Việt như "cây xăng" (docs/10 của app) |
| **Nominatim** | Geocoding và địa chỉ đầy đủ; nguồn để tự dựng Photon. Hiện chưa cần | `mediagis/nominatim:5.3` (cổng 8080; `PBF_URL`, cập nhật qua `REPLICATION_URL`) | chưa đo. [Ước] 0,5–2 giờ | chưa đo. Hành tinh 2020, style `full`: 640 GB, sau khi bỏ phần động còn 330 GB [Trích]. Tỉ lệ theo VN: [Ước] 4–10 GB | tối thiểu 2 GB [Trích]; [Ước] 2–4 GB khi import | | diff hằng ngày Geofabrik: `NOMINATIM_REPLICATION_URL=…/asia/vietnam-updates`, `nominatim replication --once` theo systemd timer [Trích] | trung bình–cao (PostgreSQL) | GPL-3.0 | **khả thi có điều kiện**: chỉ khi cần địa chỉ chi tiết hoặc tự dựng Photon. Chưa nên làm |
| **Pelias** | Geocoding trộn nhiều nguồn (OSM, OpenAddresses, WOF, CSV/Overture) | `pelias/docker` (nhiều container, có Elasticsearch) | chưa đo | "tens of GB" khi tải nguồn [Trích] | "At least 8GB RAM is required" [Trích] | | import lại theo từng nguồn | cao | MIT | **không khả thi** trên máy hiện tại (RAM), và quá nặng so với nhu cầu |
| **Overpass API** | Truy vấn thẻ OSM (ví dụ đếm quán cà phê). App không cần | không có image chính thức (có image cộng đồng `wiktorn/overpass-api`) | chưa đo | hành tinh ≥ 250 GB khi có diff phút [Trích]; [Ước] VN < 5 GB | "at least 4 GB of RAM" [Trích] | | diff (`fetch_osc.sh` + `apply_osc_to_db.sh`) [Trích] | trung bình | AGPL-3.0 | **khả thi có điều kiện**, nhưng không cần cho Lữ Trình. Khi cần nghiên cứu dữ liệu thì chạy trên máy Mac |

**Kết luận chung: khả thi có điều kiện.** Nên làm Valhalla, bản đồ vector (Planetiler + Martin) và
Photon. Không làm OSRM, Nominatim, Pelias, Overpass ở giai đoạn này.

## 5. Sức chứa Proxmox và CT 106 (quan sát chỉ đọc, 2026-11-11 02:51 UTC)

Chỉ dùng lệnh đọc. Không tạo, sửa, khởi động hay dừng gì.

- Proxmox: không có khóa SSH (`ssh -o BatchMode=yes root@192.168.31.48` →
  `Permission denied (publickey,…)`), nên đọc qua API REST. Đăng nhập bằng tài khoản quản
  trị lấy phiếu phiên; thông tin đăng nhập không ghi ở đây. Sau đó chỉ gọi `GET`.
- CT 106: `ssh mate-server '…'`.

### Máy Proxmox `promox` (Proxmox VE 8.3.0)

| Mục | Giá trị | Nguồn |
| --- | --- | --- |
| CPU | Intel Core i5-8500T, 1 socket, 6 nhân / 6 luồng | `GET /nodes/promox/status` |
| RAM | 15,4 GiB tổng; 6,4 GiB đang dùng; 1,9 GiB trống (phần còn lại là cache) | như trên |
| Swap | 8,0 GiB, đang dùng 0,2 GiB | như trên |
| Tải | loadavg 0,61 / 0,90 / 1,04 | như trên |
| 7 ngày qua | CPU cao nhất 100 % (các mẫu MAX trung bình 20,5 %); RAM dùng cao nhất **11,5 GiB**; iowait cao nhất 25,4 % | `GET /nodes/promox/rrddata?timeframe=week&cf=MAX` (63 mẫu) |
| Ổ đĩa | **một** NVMe WDC WDS500G2B0C 500 GB, SMART PASSED | `GET /nodes/promox/disks/list` |
| `local-lvm` (thin) | 337,9 GiB; đã ghi 135,8 GiB; **còn 202,0 GiB**; metadata 65/3 528 MiB | `GET /nodes/promox/storage`, `/disks/lvmthin` |
| VG `pve` | 464,8 GiB, còn 16,0 GiB chưa cấp | `GET /nodes/promox/disks/lvm` |
| `local` (dir: backup, iso, template) | 93,9 GiB, còn 55,0 GiB | `GET /nodes/promox/storage` |
| `truenas_frigate` (NFS) | **không hoạt động** (`active 0`) | như trên |

Các guest, theo `GET /cluster/resources?type=vm`:

| ID | Loại | Tên | Trạng thái | CPU | RAM cấp | Đĩa cấp (đã dùng) |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | lxc | nginxproxymanager | chạy | 1 | 0,5 GiB | 3,9 (2,8) GiB |
| 101 | lxc | adguard | chạy | 1 | 0,5 GiB | 6,8 (0,9) GiB |
| 102 | lxc | homebridge | chạy | 1 | 1,0 GiB | 3,9 (2,4) GiB |
| 104 | lxc | jellyfin | dừng | 4 | 8,0 GiB | 70 GiB |
| 105 | lxc | docker-root | chạy | 2 | 4,0 GiB | 15,6 (10,7) GiB |
| **106** | **lxc** | **docker** (= `mate-server`) | chạy | 4 | 8,0 GiB | 181 (61,1) GiB |
| 110–112 | qemu | k3s-master, k3s-worker-1/2 | dừng | 2+2+2 | 4+3+3 GiB | 3 × 20 GiB |
| 150 | qemu | android-vietmap-capture | dừng | 4 | 6,0 GiB | 20 GiB |
| 9000 | qemu | ubuntu-22.04-template | dừng | 1 | 2,0 GiB | 20 GiB |

Nhận xét:

- Các CT đang chạy đã được cấp **14,0 GiB** RAM trên tổng 15,4 GiB. Thực tế đang dùng 6,4 GiB,
  tuần qua cao nhất 11,5 GiB. RAM của LXC là giới hạn trên, không phải phần giữ chỗ, nên vẫn cấp
  thêm được. Nhưng nếu bật lại jellyfin (8 GiB) hoặc cụm k3s (10 GiB) thì máy sẽ thiếu RAM.
- Tổng đĩa đã cấp trên `local-lvm` khoảng 392 GiB (gồm cả `mp0` 8 GiB của CT 106), lớn hơn pool
  337,9 GiB: thin pool đang cấp vượt. Dung lượng còn ghi được thật là 202 GiB.

### CT 106 (`mate-server`, 192.168.31.56)

Cấu hình đọc bằng `GET /nodes/promox/lxc/106/config`: Debian, unprivileged,
`features: keyctl=1,nesting=1` (Docker chạy trong LXC), 4 nhân, 8 GiB RAM + 4 GiB swap,
`rootfs local-lvm:vm-106-disk-0,size=184G`, `mp0` 8 GB `/mnt/media`, `mp1` là thư mục NFS
`/mnt/frigate_storage`.

Lệnh `ssh mate-server 'nproc; free -h; df -h …; docker ps; docker stats --no-stream; cat /proc/loadavg; du -sh /var/lib/docker /var/lib/lutrinh'`:

```text
nproc                → 4
Mem:   total 8.0Gi  used 2.3Gi  free 1.8Gi  buff/cache 4.0Gi  available 5.7Gi
Swap:  4.0Gi  used 0B
/dev/mapper/pve-vm--106--disk--0  182G  62G  113G  36% /
loadavg              → 1.17 0.99 1.06
docker ps            → 22 container đang chạy (lutrinh app/worker/caddy, mate-web, shopee-*, mexc-*,
                       mattermost, rocketchat + mongo, nginx-proxy-manager, portainer …)
docker stats         → lớn nhất: rocketchat 755 MiB, shopee-selenium 319 MiB, nginx-proxy-manager 284 MiB
/var/lib/docker 23G, /var/lib/lutrinh 26M
```

Chỗ "What we already know" gọi là "VM/CT 106": thực ra đây là **CT (LXC)**, không phải VM.

## 6. Kế hoạch triển khai đề xuất

Các bước dưới đây chưa làm gì. Mọi thay đổi trên Proxmox, CT hoặc máy chủ phải chờ thuyền trưởng
quyết định.

**Nguyên tắc: dựng ở nơi khác, Proxmox chỉ phục vụ.** Lúc dựng cần RAM cao (Valhalla 5 GiB, OSRM
> 7,6 GiB), lúc phục vụ thì nhẹ. Trên máy Mac, mỗi tuần dựng lại cả hai thứ mất dưới 6 phút.
Sau đó chép sang máy chủ khoảng 1,6 GB: `vietnam.pmtiles` 320 MB, `valhalla_tiles.tar` 1,1 GB,
`timezones.sqlite` 128 MB, `admins.sqlite` 12 MB, và chỉ mục Photon 182 MB.

**Thứ tự:**

1. **Valhalla trước.** Đây là lợi ích rõ nhất: bỏ giới hạn 1 yêu cầu/giây, không phụ thuộc
   FOSSGIS. Server đổi mà không cần sửa mã:
   - `LUTRINH_VALHALLA_URL=http://<host>:8002/route`
   - giảm `LUTRINH_ROUTER_MIN_INTERVAL_SECONDS` (pydantic-settings, `env_prefix="LUTRINH_"`)
   - giữ OSRM FOSSGIS làm dự phòng như hiện nay.

   App phải sửa `Routers.kt` (ngoài phạm vi task này) và cần một địa chỉ HTTPS công khai sau
   Cloudflare → NPM, có giới hạn tốc độ. Phương án khác: app chỉ đường qua route server.
2. **Bản đồ vector.** Planetiler → `vietnam.pmtiles`, phục vụ bằng Martin. Dùng kiểu `positron`
   của OpenFreeMap (cùng lược đồ OpenMapTiles), font và sprite tự host. App đổi URL style trong
   `OpenFreeMap.kt` (ngoài phạm vi). Ảnh vệ tinh Esri vẫn lấy từ ngoài; OSM không có ảnh vệ tinh.
3. **Photon**, khi làm ô tìm kiếm trực tuyến qua server ("Bước 3" trong docs/10 của app). Nên đặt
   sau route server, không mở trực tiếp ra Internet.

**Đặt ở đâu.** Cần quyết định, chưa chọn. Hai phương án:

- (a) **CT mới riêng** (ví dụ `osm`): 2 nhân, 3–4 GiB RAM, 20–30 GB đĩa trên `local-lvm`.
  - Tách khỏi 22 container của CT 106.
  - Tắt hay khôi phục độc lập; có thể đặt `backup=0` cho mount dữ liệu.
  - Mất thêm phần quản trị cho một CT nữa.
- (b) **Thêm vào CT 106**.
  - CT 106 còn 113 GB đĩa, 5,7 GiB RAM khả dụng, 4 nhân.
  - Chỉ phục vụ thì vừa (khoảng 1–2 GiB).
  - Không nên dựng ngay trong CT 106: Valhalla dựng với 8 luồng chiếm 5 GiB, sẽ chèn các dịch vụ
    khác.

Cả hai phương án đều phải tính RAM toàn máy (mục 5).

**Sao lưu.** Mọi tệp dữ liệu (`.pmtiles`, `valhalla_tiles.tar`, chỉ mục Photon) đều dựng lại được
từ pbf, nên **không đưa vào restic**. Chỉ lưu kịch bản dựng, cấu hình và style (trong git). Trên
máy chủ giữ hai thư mục "hiện tại" và "trước đó", đổi qua symlink để quay lui trong vài giây.

**Cập nhật.** Mỗi tuần (hoặc khi cần) tải pbf mới (33 giây), dựng lại, chép sang, tráo thư mục rồi
khởi động lại container. Không cần diff hằng ngày cho mục đích du lịch.

**Hoàng Sa / Trường Sa khi tự làm tile:**

- Bản trích Việt Nam **không có dữ liệu OSM** cho Hoàng Sa và phần lớn Trường Sa (mục 1).
  - Hệ quả tốt: tile không có tên hành chính Trung Quốc (三沙市 …) ở đó.
  - Hệ quả xấu: tile cũng không có tên đảo tiếng Việt (`name:vi`). Hình đảo vẫn hiện, vì lớp nước
    lấy từ water polygons toàn cầu (suy luận, chưa mở tile để xem).
- Nhãn "Quần đảo Hoàng Sa" và "Quần đảo Trường Sa" do app tự vẽ, nên vẫn còn.
- Nếu muốn có tên đảo:
  - trộn thêm một phần cắt OSM quanh hai quần đảo (cắt từ bản trích lớn hơn bằng `osmium extract`
    theo đa giác riêng);
  - lọc R30 ngay khi dựng (profile Planetiler) hoặc giữ bộ lọc R30 hiện có của app và admin. Bộ lọc
    này viết cho lược đồ OpenMapTiles nên áp được nguyên;
  - trộn dữ liệu rồi phát hành tile là "produced work": vẫn chỉ cần ghi công ODbL.
- Photon (bản dump GraphHopper) trả "Trường Sa" → Khánh Hòa [Đo]. Chưa thử "Hoàng Sa".

**Ngoài biên giới.** Tile chỉ từ bản trích Việt Nam sẽ trống ở Lào, Campuchia và Trung Quốc từ mức
zoom trung bình trở lên (Natural Earth chỉ phủ zoom thấp). Valhalla cũng không chỉ đường qua biên
giới. Nếu có hành trình xuyên biên giới thì phải chọn một trong hai:

- ghép thêm bản trích các nước lân cận (Laos, Cambodia, …: dữ liệu lớn hơn, dựng lâu hơn);
- giữ OpenFreeMap và FOSSGIS làm dự phòng ngoài vùng.

## 7. Rủi ro

- **RAM toàn máy**: đã cấp 14/15,4 GiB, đỉnh tuần 11,5 GiB. Thêm dịch vụ mà lại bật jellyfin hoặc
  k3s thì máy có thể phải dùng swap hoặc kích hoạt OOM.
- **Một ổ NVMe duy nhất**, không có dự phòng phần cứng. NFS `truenas_frigate` không hoạt động. Thin
  pool cấp vượt (khoảng 392 GiB cấp trên 337,9 GiB): đầy pool thì mọi guest bị lỗi ghi.
- **Dựng trên máy yếu có thể hết RAM**: OSRM bị kill ở 7,6 GiB [Đo]. Valhalla cần 5 GiB với 8
  luồng [Đo].
- **Docker trong LXC unprivileged** (`nesting=1`): hiện chạy ổn, nhưng các image đọc/ghi mmap lớn
  (Valhalla tar, OpenSearch nhúng trong Photon) chưa được thử trong CT này.
- **Mở dịch vụ ra Internet**: Valhalla và Photon không có xác thực. Nếu app gọi trực tiếp thì phải
  có giới hạn tốc độ (Cloudflare/NPM), nếu không máy dễ bị quá tải.
- **Chất lượng dữ liệu OSM ở Việt Nam**: POI mỏng (docs/10 của app). Tự host không làm dữ liệu dày
  hơn.
- **Ghi công**: phải hiện "© OpenStreetMap contributors" và "© OpenMapTiles" trên bản đồ.
- **Bảo trì**: thêm 2–3 container và một lịch dựng hằng tuần. Nếu lịch dựng hỏng thì dữ liệu cũ
  dần, nhưng dịch vụ vẫn chạy.
- **R30**: dữ liệu ghép thêm quanh hai quần đảo sẽ mang tên Trung Quốc vào. Phải lọc và có kiểm
  thử ảnh chụp (như `r30-*.png` của admin e2e).

## 8. Cách tái lập số liệu

```sh
R=/Volumes/wdblack/tmp/research-osm-selfhost
curl -sSL -o $R/data/vietnam-latest.osm.pbf https://download.geofabrik.de/asia/vietnam-latest.osm.pbf
docker run --rm -e JAVA_TOOL_OPTIONS=-Xmx4g -v $R/planetiler/data:/data ghcr.io/onthegomap/planetiler:latest \
  --area=vietnam --osm-path=/data/sources/vietnam.osm.pbf --download --output=/data/vietnam.pmtiles --tmpdir=/data/tmp
docker run --rm -e serve_tiles=False -e build_elevation=False -e server_threads=8 \
  -v $R/valhalla/custom_files:/custom_files ghcr.io/valhalla/valhalla-scripted:latest   # pbf đặt trong custom_files/
zstd --stdout -d photon-dump-vietnam-1.0-latest.jsonl.zst | docker run -i --rm -v $R/photon/dl:/app:ro \
  -v $R/photon/data:/data -w /data eclipse-temurin:21-jre java -jar /app/photon.jar import -import-file - -languages vi,en -data-dir /data
```

Log: `$R/planetiler/run.log`, `$R/valhalla/run.log` (+ `stats.log`), `$R/photon/import.log`,
`$R/osrm/run.log`.

## 9. Nguồn (tất cả truy cập 2026-11-11)

- [S1] Geofabrik Việt Nam: https://download.geofabrik.de/asia/vietnam.html
- [S2] Geofabrik, thông tin kỹ thuật (cập nhật hằng ngày, diff, ODbL, bỏ metadata): https://download.geofabrik.de/technical.html
- [S3] Planetiler README (yêu cầu phần cứng, giấy phép, ghi công OpenMapTiles): https://github.com/onthegomap/planetiler
- [S4] Martin: https://maplibre.org/martin/
- [S5] Valhalla Docker README (biến môi trường, dựng lại): https://github.com/valhalla/valhalla/blob/master/docker/README.md
- [S6] OSRM backend README (image, lệnh, giấy phép): https://github.com/Project-OSRM/osrm-backend
- [S7] Photon README và docs/usage.md: https://github.com/komoot/photon, https://github.com/komoot/photon/blob/master/docs/usage.md
- [S8] Bản dump Photon Việt Nam: https://download1.graphhopper.com/public/asia/vietnam/
- [S9] Nominatim 5.3.3, cài đặt, import, cập nhật: https://nominatim.org/release-docs/latest/admin/Installation/, …/admin/Import/, …/admin/Update/
- [S10] nominatim-docker (`mediagis/nominatim:5.3`): https://github.com/mediagis/nominatim-docker
- [S11] Pelias docker: https://github.com/pelias/docker
- [S12] FOSSGIS routing, mục "Usage policy": "One request per second max. No scraping, no heavy usage." https://routing.openstreetmap.de/about.html; điều khoản đầy đủ: https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen (trang này chặn bot khi truy cập; chỉ đọc được qua kết quả tìm kiếm)
- [S15] Giấy phép phần mềm: GitHub API `repos/<repo>/license` (martin Apache-2.0, Nominatim GPL-3.0, Overpass-API AGPL-3.0, pelias/docker MIT, photon Apache-2.0, planetiler Apache-2.0, osrm-backend BSD-2-Clause); Valhalla: tệp `COPYING` "The MIT License"
- [S13] Overpass API, cài đặt tối giản: https://dev.overpass-api.de/no_frills.html
- [S14] Nghiên cứu trước về nhà cung cấp tìm địa điểm: `polarsteps-clone-native/docs/10-place-search-providers.md` (commit 0252342)
