# LLM File Translator

Dịch tự động file Google Sheets, Google Docs, và file local (.xlsx, .docx, .txt) sang ngôn ngữ khác bằng LLM (AI).

---

## Tính năng

- Dịch **Google Sheets** — toàn bộ sheet hoặc chỉ 1 sheet cụ thể
- Dịch **Google Docs**
- Dịch **file local**: `.xlsx`, `.docx`, `.txt`
- Tự động **nhân bản file gốc** trước khi dịch (file gốc không bị ảnh hưởng)
- Ghi kết quả dịch **ngay lập tức** theo từng chunk (không mất dữ liệu nếu bị gián đoạn)
- Retry tự động không giới hạn khi bị rate limit (429)
- Hỗ trợ nhiều LLM provider: **NVIDIA NIM**, **OpenRouter**

---

## Yêu cầu

- Python **3.11** trở lên (khuyến nghị 3.11 hoặc 3.12, không dùng 3.14 beta)
- Tài khoản Google (để dịch Google Drive files)
- API key của LLM provider

---

## Cài đặt

### 1. Tạo virtual environment

```powershell
# Dùng Python 3.11
C:\Users\<username>\AppData\Local\Programs\Python\Python311\python.exe -m venv C:\venv\llm-file-translator
```

### 2. Cài dependencies

```powershell
C:\venv\llm-file-translator\Scripts\pip.exe install -r requirements.txt
```

### 3. Chạy ứng dụng

Bấm đúp `run.bat`, hoặc:

```powershell
C:\venv\llm-file-translator\Scripts\python.exe ui.py
```

---

## Thiết lập lần đầu

Lần đầu chạy sẽ hiện wizard tự động:

### Bước 1 — Chọn LLM Provider

| Provider | Đặc điểm |
|---|---|
| **NVIDIA NIM** | Tốc độ cao, rate limit 40 req/min |
| **OpenRouter** | Nhiều model, có free tier (20 req/min) |

### Bước 2 — Nhập API Key

- **NVIDIA NIM**: lấy tại [build.nvidia.com](https://build.nvidia.com) → Get API Key
- **OpenRouter**: lấy tại [openrouter.ai/keys](https://openrouter.ai/keys)

### Bước 3 — Chọn model

Chọn từ danh sách hoặc nhập model ID tùy chỉnh.

> Cài đặt được lưu vào file `.env` và sẽ nhớ cho các lần chạy sau.

---

## Thiết lập Google OAuth (cho Google Drive)

Cần thực hiện **1 lần duy nhất**:

1. Vào menu **[1] Google認証 (Auth Setup)**
2. Trình duyệt sẽ mở ra → đăng nhập Google → cấp quyền
3. Token được lưu tại `config/google_token.json`

> Cần có file `config/google_credentials.json` (OAuth 2.0 credentials từ Google Cloud Console) trước khi thực hiện bước này.

---

## Cách sử dụng

### Dịch Google Sheets / Docs

1. Chọn **[2] Googleファイルを翻訳**
2. Dán URL hoặc File ID của file Google (1 dòng 1 file), Enter trống để kết thúc
3. Nhập ngôn ngữ đích (mặc định: `Japanese`)
4. Nhập tên sheet cụ thể nếu muốn (để trống = dịch tất cả sheet)

**Ví dụ URL hợp lệ:**
```
https://docs.google.com/spreadsheets/d/1ABC.../edit
https://docs.google.com/document/d/1XYZ.../edit
```

File clone sẽ được tạo trong cùng thư mục với tên gốc + suffix ngôn ngữ:
```
MyFile.xlsx  →  MyFile-jp.xlsx
```

### Dịch file local (.xlsx / .docx / .txt)

1. Chọn **[3] ローカルファイルを翻訳**
2. Chọn file qua dialog hoặc nhập đường dẫn thủ công
3. Nhập ngôn ngữ đích và tên sheet (nếu là .xlsx)

---

## Ngôn ngữ hỗ trợ

Nhập tên ngôn ngữ bằng tiếng Anh. Một số ví dụ:

| Tên nhập | Suffix file |
|---|---|
| `Japanese` | `-jp` |
| `Vietnamese` | `-vn` |
| `English` | `-en` |
| `Korean` | `-ko` |
| `Chinese` | `-zh` |
| `Thai` | `-th` |

---

## Cell/nội dung không được dịch

Các nội dung sau bị bỏ qua (không gửi lên LLM):

| Loại | Ví dụ |
|---|---|
| Ký tự quá ngắn (≤ 2) | `OK`, `No`, `ID` |
| Chỉ toàn số/ký hiệu | `123`, `36-11`, `100%` |
| Công thức Sheets | `=SUM(A1:A10)` |
| URL | `https://example.com` |
| Email | `user@example.com` |
| Ngày dạng ISO | `2024-01-01` |

---

## Log

Mỗi lần chạy tạo 1 file log trong thư mục `logs/`:

```
logs/
  translate_20260525_211323.log   ← log từng lần dịch Google
  translate_local_20260526_...log ← log từng lần dịch local
  crash.log                       ← crash không bắt được (nếu có)
```

Log ghi timestamp, tiến độ từng chunk, lỗi kèm traceback đầy đủ.

---

## Cài đặt LLM (menu [5])

Có thể đổi provider, API key, model bất kỳ lúc nào qua menu **[5] LLMプロバイダー設定**.

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `429 Too Many Requests` | Vượt rate limit LLM | Tự động retry, không cần làm gì |
| `Google token not found` | Chưa xác thực Google | Chạy menu [1] Auth Setup |
| `File not accessible` | Không có quyền truy cập file | Kiểm tra quyền chia sẻ Google Drive |
| Process tự dừng | Heap corruption (Python 3.14) | Dùng Python 3.11 + `run.bat` |
