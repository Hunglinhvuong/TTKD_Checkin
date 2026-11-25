# Telegram Attendance — Giai đoạn 1 (nền tảng)

## Cài đặt
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # điền DATABASE_URL, ADMIN_TELEGRAM_IDS
```

## PostgreSQL (tạo DB)
```sql
CREATE USER attendance WITH PASSWORD 'change_me';
CREATE DATABASE attendance OWNER attendance;
CREATE DATABASE attendance_test OWNER attendance;
```

## Chạy
```bash
python main.py check     # kiểm tra kết nối
python main.py migrate   # áp dụng migrations
python main.py seed      # nạp admin từ ADMIN_TELEGRAM_IDS
python -m scripts.check_db
pytest                   # integration test chạy khi có TEST_DATABASE_URL (XÓA SẠCH schema public của DB test)
```

## Quy ước
- Migration mới: `database/migrations/NNN_ten.sql`; không sửa file đã áp dụng (checksum sẽ báo lỗi).
- Timestamp lưu UTC (`TIMESTAMPTZ`); chuyển `Asia/Ho_Chi_Minh` ở tầng ứng dụng.
- Backup: `pg_dump -Fc attendance > backup_$(date +%F).dump` (cron hằng ngày, chi tiết ở Giai đoạn 7).

## Giai đoạn 3 — Tiếp nhận điểm danh
- `.env`: thêm `CLOUDINARY_*` (bắt buộc), `ATTENDANCE_CHAT_IDS` (khuyến nghị: ID group điểm danh), `UPLOAD_TMP_DIR`.
- Ngày nghỉ: `python -m scripts.seed_holidays 2027` (chỉ ngày dương lịch cố định). Tết, Giỗ Tổ, nghỉ bù: admin dùng
  `/holiday add|work|del|list` trong Telegram.
- Ảnh upload lên Cloudinary dạng `authenticated` (không công khai); xem ảnh qua `photo_storage.signed_url()`.
- Ảnh tạm trong `UPLOAD_TMP_DIR` được giữ cho worker OCR và sẽ được dọn sau khi xử lý xong.
- Upload lỗi sẽ tự thử lại mỗi 5 phút (tối đa 5 lần).

## Giai đoạn 4 — Đọc thông tin ảnh bằng OCR.Space
```bash
pip install -r requirements.txt
python main.py worker                     # chạy worker (tiến trình riêng với bot)
```
- Cấu hình `OCR_SPACE_API_KEY`; worker nghỉ `OCR_SPACE_MIN_INTERVAL_S` giữa các lượt và chỉ một worker chạy cùng lúc.
- Mặc định giới hạn ảnh 1 MB theo gói miễn phí (`OCR_SPACE_MAX_FILE_BYTES`); tăng cấu hình nếu gói OCR.Space cho phép file lớn hơn. Ảnh JPG/PNG được gửi nguyên bản tới OCR.Space.
- Worker dùng OCR.Space để đọc thời gian và thông tin ảnh. Chỉ thời gian chụp được dùng để xác định ảnh thuộc buổi sáng hay chiều; GPS không được kiểm tra và không có đánh giá đúng giờ/muộn.
- **OCR chỉ đọc nội dung ảnh, không xác thực ảnh nguyên bản hoặc phát hiện chỉnh sửa.** Check-in hoàn tất sau khi có cả thời gian ảnh đúng buổi và tên điểm bán.
- Ảnh điểm danh được gửi tới dịch vụ OCR.Space bên ngoài; chỉ bật nếu chính sách quyền riêng tư của bạn cho phép.
- Admin (chat riêng với bot): `/review`, `/resolve <id> VALID|LATE|REJECTED <lý do>`, `/reverify <id> <lý do>`.
- Ảnh tạm được xóa sau khi xác minh xong và ảnh đã có trên Cloudinary.
- Migration `009_ocr_schema_cleanup.sql` dọn dữ liệu và trường lưu trữ không còn dùng; log OCR, quyết định admin và audit điểm danh vẫn được giữ.

## Giai đoạn 5 — Ghi nhận điểm bán
Sau khi nhận ảnh, bot thông báo ngày/buổi check-in theo thời điểm nhận ảnh và yêu cầu nhân viên nhập tên điểm bán. Chỉ sau khi đã đọc được
thời gian ảnh và nhập tên điểm bán, hệ thống mới hoàn tất và thông báo kết quả check-in. Check-in hợp lệ khi thời gian trên ảnh thuộc đúng buổi;
không kiểm tra tọa độ GPS hoặc tính đúng giờ/muộn, trạng thái giờ giấc được để `NOT_EVALUATED`. Nếu OCR hoàn tất trước khi nhập tên, kết quả sẽ
được gửi sau khi nhập tên; nếu nhập tên trước thì kết quả được gửi khi OCR hoàn tất.

## Giai đoạn 6 — Dashboard (Streamlit Cloud)
- **Xem: không cần đăng nhập**. Khi đưa lên mạng, mọi người có thể xem tên, ảnh và tọa độ nhân viên; chỉ triển khai công khai nếu bạn chấp nhận việc này.
- **Sửa: tài khoản/mật khẩu riêng** được cấu hình trong Streamlit Secrets, gắn với Telegram ID admin đang hoạt động (vai trò ADMIN/SUPER_ADMIN). Không dùng BOT_TOKEN, không gọi Telegram API và không gửi thông báo Telegram từ dashboard. Phiên hết hạn sau 8 giờ.
- SUPER_ADMIN thêm/khóa admin ở trang "Quản trị admin"; để cấp tài khoản dashboard, thêm mục tương ứng vào `dashboard_users` trong Streamlit Secrets. Quyền vẫn được kiểm tra lại theo bảng `admins`, các thao tác được audit với nguồn `DASHBOARD`.
- Mọi truy vấn xem chạy trong transaction READ ONLY và tham số hóa; dữ liệu lấy trực tiếp từ PostgreSQL (không dùng CSV).
- Triển khai `dashboard/app.py` trên Streamlit Cloud; cấu hình PostgreSQL, Cloudinary và tài khoản trong Streamlit Secrets theo [docs/VAN_HANH.md](docs/VAN_HANH.md).

`deploy/install.sh` chỉ cài bot và worker trên máy chủ Ubuntu; không cài dịch vụ dashboard.

## Bổ sung
- **Thư mục Cloudinary**: đặt `CLOUDINARY_FOLDER` trong `.env` (mặc định `attendance`). Ảnh mới lưu tại `<thư mục>/<YYYY-MM-DD>/<user>_<buổi>_<id>`
  (loại `authenticated`). Đổi thư mục chỉ ảnh upload sau đó theo thư mục mới; ảnh cũ giữ nguyên `public_id` đã lưu trong DB.
  `CLOUDINARY_SET_ASSET_FOLDER=true` (mặc định) đặt thêm `asset_folder` để ảnh hiện trong thư mục ở Media Library; nếu tài khoản
  Cloudinary ở chế độ "fixed folder" và upload báo lỗi `asset_folder` thì đặt `false`.
- Mọi ảnh có trạng thái `REJECTED`, kể cả ảnh admin chủ động từ chối, có thể được thay thế. Giới hạn là 3 ảnh tổng cộng/buổi (kể cả ảnh
  đầu tiên); khi thay thế, ảnh cũ được giữ làm lịch sử và đánh dấu bị thay thế.

## Giai đoạn 7 — Triển khai, sao lưu, vận hành
Xem **docs/VAN_HANH.md**. Tóm tắt (Debian/Ubuntu, dịch vụ chạy trực tiếp từ thư mục dự án):
```bash
sudo ./deploy/install.sh        # lần đầu tạo .env; điền xong chạy lại để cài .venv, migrate, dịch vụ systemd, timer
.venv/bin/python main.py doctor # kiểm tra sức khỏe
./deploy/backup.sh              # sao lưu; khôi phục: ./deploy/restore.sh <file.dump>
./deploy/run_tests.sh           # test (cần TEST_DATABASE_URL riêng)
```
