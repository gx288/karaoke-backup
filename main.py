import os
import sys
import json
import time
import datetime
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from proxy_manager import get_working_proxy

# === CONFIGURATION FROM ENV VARS ===
OAUTH_TOKEN_JSON = os.environ.get('GOOGLE_OAUTH_TOKEN')
SOURCE_PLAYLIST_IDS = os.environ.get('SOURCE_PLAYLIST_IDS')
TARGET_PLAYLIST_ID = os.environ.get('TARGET_PLAYLIST_ID')
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
SHEET_RANGE = 'Sheet1!A:E'

def get_credentials():
    if not OAUTH_TOKEN_JSON:
        print("[!] Không tìm thấy GOOGLE_OAUTH_TOKEN trong biến môi trường.")
        sys.exit(1)
    
    token_dict = json.loads(OAUTH_TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(token_dict)
    return creds

def get_youtube_service(creds):
    return build('youtube', 'v3', credentials=creds)

def get_sheets_service(creds):
    return build('sheets', 'v4', credentials=creds)

def read_processed_videos(sheets_service):
    print("[*] Đang đọc danh sách video đã backup từ Google Sheets...")
    try:
        sheet = sheets_service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        
        # Cột A là Link Gốc (chứa video ID)
        processed_ids = []
        for row in values[1:]: # Bỏ qua header
            if len(row) > 0:
                link = row[0]
                # Lọc ID từ link
                if "v=" in link:
                    vid_id = link.split("v=")[1].split("&")[0]
                    processed_ids.append(vid_id)
        return processed_ids
    except Exception as e:
        print(f"[-] Lỗi đọc Sheets: {e}")
        return []

def get_playlist_videos(youtube, playlist_id):
    print(f"[*] Lấy danh sách video từ playlist nguồn: {playlist_id}")
    videos = []
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    )
    
    while request is not None:
        response = request.execute()
        for item in response['items']:
            title = item['snippet']['title']
            video_id = item['snippet']['resourceId']['videoId']
            videos.append({'id': video_id, 'title': title})
        
        request = youtube.playlistItems().list_next(request, response)
        
    return videos

def download_video(video_id, proxy):
    print(f"[*] Đang tải video: {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_tmpl = f"{video_id}.mp4"
    
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        url
    ]
    
    if proxy:
        print(f"[*] Sử dụng proxy: {proxy}")
        cmd.extend(["--proxy", proxy])
        
    # Thêm tuỳ chọn dùng cookie nếu user có truyền vào cookies.txt qua env
    if os.path.exists("cookies.txt"):
        print("[*] Tìm thấy cookies.txt, sẽ sử dụng để bypass giới hạn")
        cmd.extend(["--cookies", "cookies.txt"])
        
    try:
        subprocess.run(cmd, check=True)
        return out_tmpl if os.path.exists(out_tmpl) else None
    except subprocess.CalledProcessError as e:
        print(f"[-] Lỗi khi tải video bằng yt-dlp: {e}")
        return None

def upload_video_to_youtube(youtube, file_path, title, description):
    print(f"[*] Bắt đầu upload file {file_path} lên YouTube...")
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'categoryId': '10' # Music
        },
        'status': {
            'privacyStatus': 'private' # Đặt private để không bị public ngay, hoặc 'unlisted'
        }
    }
    
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  [+] Uploading... {int(status.progress() * 100)}%")
            
    print(f"[+] Upload thành công! Video ID mới: {response['id']}")
    return response['id']

def add_to_playlist(youtube, playlist_id, video_id):
    print(f"[*] Thêm video {video_id} vào playlist phụ {playlist_id}...")
    request = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    )
    request.execute()
    print("[+] Đã thêm vào playlist!")

def log_to_sheets(sheets_service, original_id, new_id, title):
    print("[*] Ghi log vào Google Sheets...")
    original_link = f"https://www.youtube.com/watch?v={original_id}"
    new_link = f"https://www.youtube.com/watch?v={new_id}"
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    values = [[original_link, new_link, title, date_str, "Thành công"]]
    body = {'values': values}
    
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=SHEET_RANGE,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()
    print("[+] Đã ghi log thành công!")

def main():
    if not all([SOURCE_PLAYLIST_IDS, TARGET_PLAYLIST_ID, SHEET_ID]):
        print("[!] Thiếu cấu hình Environment Variables (SOURCE_PLAYLIST_IDS, TARGET_PLAYLIST_ID, SHEET_ID...)")
        sys.exit(1)
        
    creds = get_credentials()
    youtube = get_youtube_service(creds)
    sheets_service = get_sheets_service(creds)
    
    processed_ids = read_processed_videos(sheets_service)
    print(f"[*] Đã tìm thấy {len(processed_ids)} video trong lịch sử backup.")
    
    source_videos = []
    # Hỗ trợ nhiều playlist phân cách bằng dấu phẩy
    playlist_ids = [pid.strip() for pid in SOURCE_PLAYLIST_IDS.split(",") if pid.strip()]
    for pid in playlist_ids:
        source_videos.extend(get_playlist_videos(youtube, pid))
    
    new_videos = [v for v in source_videos if v['id'] not in processed_ids]
    print(f"[*] Có {len(new_videos)} video mới cần backup.")
    
    if not new_videos:
        print("[*] Không có video nào mới. Kết thúc.")
        return
        
    proxy = get_working_proxy()
    if not proxy:
        print("[!] Cảnh báo: Không lấy được proxy sống. Sẽ thử tải trực tiếp...")
        
    for video in new_videos:
        vid_id = video['id']
        title = video['title']
        print(f"\n=========================================")
        print(f"[*] Đang xử lý: {title} ({vid_id})")
        
        file_path = download_video(vid_id, proxy)
        if not file_path:
            print(f"[-] Bỏ qua video {vid_id} do lỗi tải.")
            continue
            
        try:
            desc = f"Backup từ video gốc: https://www.youtube.com/watch?v={vid_id}"
            new_id = upload_video_to_youtube(youtube, file_path, f"[BACKUP] {title}", desc)
            
            add_to_playlist(youtube, TARGET_PLAYLIST_ID, new_id)
            log_to_sheets(sheets_service, vid_id, new_id, title)
            
        except Exception as e:
            print(f"[-] Quá trình upload bị lỗi: {e}")
            
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[*] Đã xóa file tạm {file_path}")
                
        # Nghỉ chút để tránh limit
        time.sleep(10)

if __name__ == '__main__':
    main()
