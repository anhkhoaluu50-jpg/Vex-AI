# Vex Code AI — starter cho Render

Chatbot lập trình tiếng Việt có đăng ký/đăng nhập, lịch sử chat, upload file văn bản/code, giao diện responsive và nút copy code.

## Triển khai nhanh trên Render

1. Tải ZIP, giải nén và đẩy toàn bộ nội dung lên một GitHub repo mới.
2. Trên Render chọn **New + → Web Service**, kết nối repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Environment:
   - `LLM_BASE_URL` = `https://openrouter.ai/api/v1`
   - `LLM_API_KEY` = API key riêng của bạn
   - `LLM_MODEL` = ID model chính xác lấy từ danh sách model của nhà cung cấp
   - `APP_SECRET` = chuỗi bí mật dài, ngẫu nhiên (Render có thể tạo tự động qua `render.yaml`)
6. Deploy rồi mở URL Render.

Bạn có thể dùng `render.yaml` để cấu hình service bằng Blueprint. Không đưa API key vào mã nguồn hoặc GitHub.

## Ghi chú quan trọng

- Cơ chế tài khoản ở bản starter dùng SQLite và mật khẩu băm bằng scrypt; token đăng nhập có thời hạn 14 ngày.
- Trên dịch vụ free, hệ thống file/dữ liệu cục bộ có thể không bền vững khi redeploy/restart. Nếu dùng thật, hãy chuyển SQLite sang PostgreSQL và dùng persistent storage phù hợp.
- Upload hiện hỗ trợ file văn bản/code UTF-8 tối đa 3 MB. PDF/DOCX/ZIP chưa được xử lý.
- Đây là starter project, chưa phải nền tảng production: cần bổ sung email reset mật khẩu, xác minh email, giới hạn tốc độ theo tài khoản/IP, CSRF/CORS policy, logging/monitoring và kiểm thử bảo mật trước khi mở công khai.
- Model AI, tốc độ và chi phí phụ thuộc nhà cung cấp/model và hạn mức tài khoản.
