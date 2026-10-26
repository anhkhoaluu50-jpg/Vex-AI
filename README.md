# Vex Code AI — DeepSeek Edition

Khung chatbot tiếng Việt cho lập trình và an ninh mạng được phép, có đăng ký/đăng nhập, lịch sử chat, đính kèm file văn bản/code và nút chuyển Vex Code / Vex Security. Cấu hình mặc định dành cho DeepSeek API.

## Triển khai trên Render

1. Giải nén ZIP và đẩy thư mục `vex-code-ai-deepseek` lên GitHub repository của bạn.
2. Tạo Web Service trên Render và kết nối repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Environment Variables:
   - `LLM_BASE_URL` = `https://api.deepseek.com`
   - `LLM_API_KEY` = API key lấy từ https://platform.deepseek.com/ (giữ bí mật)
   - `LLM_MODEL` = `deepseek-flash` (xác nhận model hiện được tài khoản hỗ trợ trong tài liệu chính thức)
   - `APP_SECRET` = chuỗi bí mật dài, ngẫu nhiên; có thể để Render tạo theo `render.yaml`
6. Deploy rồi thử đăng ký tài khoản và gửi tin nhắn.

Tài liệu chính thức: https://api-docs.deepseek.com/quick_start/agent_integrations/ . DeepSeek dùng định dạng API tương thích OpenAI.

## Lưu ý

- Không commit API key vào GitHub hoặc gửi key trong chat.
- API có thể tính phí; kiểm tra giá/hạn mức trong tài khoản DeepSeek.
- Bản starter dùng SQLite; dữ liệu local có thể không bền vững khi redeploy/restart trên môi trường free. Nên dùng PostgreSQL và giới hạn tốc độ trước khi mở cho nhiều người dùng.
- Chưa tích hợp cổng thanh toán thật. Credits là khung cơ bản, không phải hệ thống thanh toán hoàn chỉnh.
