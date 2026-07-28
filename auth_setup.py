import os
from google_auth_oauthlib.flow import InstalledAppFlow

# Phạm vi truy cập cần thiết: YouTube API và Google Sheets API
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]

def main():
    print("=== TOOL LẤY GOOGLE TOKEN CHO KARAOKE BACKUP ===")
    
    if not os.path.exists('client_secret.json'):
        print("[!] Không tìm thấy file client_secret.json!")
        print("[!] Vui lòng tải file này từ Google Cloud Console (chọn ứng dụng dạng Desktop App) và đặt cùng thư mục.")
        return

    flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
    
    # Chạy server local để bắt callback từ trình duyệt
    creds = flow.run_local_server(port=0)
    
    # Ghi token ra file
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())
        
    print("\n[+] THÀNH CÔNG! Đã tạo file token.json")
    print("[+] Bạn hãy sao chép TOÀN BỘ nội dung file token.json này và dán vào GitHub Secrets với tên biến là GOOGLE_OAUTH_TOKEN")

if __name__ == '__main__':
    main()
