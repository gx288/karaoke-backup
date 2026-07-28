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

OAUTH_TOKEN_JSON = os.environ.get('GOOGLE_OAUTH_TOKEN')

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

def get_first_sheet_name(sheets_service):
    """Lấy tên tab đầu tiên (tránh lỗi tên tiếng Việt 'Trang tính 1')"""
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    metadata = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return metadata.get('sheets', [])[0].get("properties", {}).get("title", "Sheet1")

def read_processed_videos(sheets_service):
    print("[*] Đang đọc danh sách video đã backup từ Google Sheets...")
    try:
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        sheet_name = get_first_sheet_name(sheets_service)
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{sheet_name}'!A:E"
        ).execute()
        values = result.get('values', [])
        processed_ids = []
        for row in values[1:]:  # Bỏ qua header
            if len(row) > 0:
                link = row[0]
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

def download_video(video_id, proxy, dead_proxies):
    """
    Tải video. Nếu proxy chết thì tự động xoay sang proxy mới.
    dead_proxies: set các proxy đã biết hỏng để truyền vào get_working_proxy
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_tmpl = f"{video_id}.mp4"
    current_proxy = proxy

    MAX_PROXY_RETRIES = 3
    for attempt in range(MAX_PROXY_RETRIES):
        print(f"[*] Đang tải video: {video_id} (lần thử {attempt + 1}/{MAX_PROXY_RETRIES})")

        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", out_tmpl,
            "--retries", "3",       # yt-dlp tự retry 3 lần rồi báo lỗi về cho mình
            "--fragment-retries", "3",
            url
        ]

        if current_proxy:
            print(f"  [*] Dùng proxy: {current_proxy}")
            cmd.extend(["--proxy", current_proxy])

        if os.path.exists("cookies.txt"):
            print("  [*] Dùng cookies.txt để bypass giới hạn")
            cmd.extend(["--cookies", "cookies.txt"])

        try:
            subprocess.run(cmd, check=True)
            if os.path.exists(out_tmpl):
                return out_tmpl, dead_proxies
        except subprocess.CalledProcessError:
            print(f"  [-] Tải thất bại với proxy {current_proxy}. Đánh dấu hỏng và tìm proxy mới...")
            if current_proxy:
                dead_proxies.add(current_proxy)
            # Tìm proxy mới, tránh dùng lại proxy hỏng
            current_proxy = get_working_proxy(exclude=dead_proxies)
            if not current_proxy:
                print("  [!] Hết proxy sống để thử. Bỏ qua video này.")
                break

    return None, dead_proxies

def upload_video_to_youtube(youtube, file_path, title, description):
    print(f"[*] Bắt đầu upload file {file_path} lên YouTube...")
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'categoryId': '10'  # Music
        },
        'status': {
            'privacyStatus': 'private'
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
    youtube.playlistItems().insert(
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
    ).execute()
    print("[+] Đã thêm vào playlist!")

def log_to_sheets(sheets_service, original_id, new_id, title):
    print("[*] Ghi log vào Google Sheets...")
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    original_link = f"https://www.youtube.com/watch?v={original_id}"
    new_link = f"https://www.youtube.com/watch?v={new_id}"
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[original_link, new_link, title, date_str, "Thành công"]]
    sheet_name = get_first_sheet_name(sheets_service)
    sheets_service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{sheet_name}'!A:E",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()
    print("[+] Đã ghi log thành công!")

def main():
    source_playlist_ids = os.environ.get('SOURCE_PLAYLIST_IDS')
    target_playlist_id = os.environ.get('TARGET_PLAYLIST_ID')
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')

    if not all([source_playlist_ids, target_playlist_id, sheet_id]):
        print("[!] Thiếu cấu hình Environment Variables.")
        sys.exit(1)

    creds = get_credentials()
    youtube = get_youtube_service(creds)
    sheets_service = get_sheets_service(creds)

    processed_ids = read_processed_videos(sheets_service)
    print(f"[*] Đã tìm thấy {len(processed_ids)} video trong lịch sử backup.")

    source_videos = []
    playlist_ids = [pid.strip() for pid in source_playlist_ids.split(",") if pid.strip()]
    for pid in playlist_ids:
        source_videos.extend(get_playlist_videos(youtube, pid))

    new_videos = [v for v in source_videos if v['id'] not in processed_ids]
    print(f"[*] Có {len(new_videos)} video mới cần backup.")

    if not new_videos:
        print("[*] Không có video nào mới. Kết thúc.")
        return

    # Khởi tạo proxy một lần, tái sử dụng + tự xoay nếu chết
    proxy = get_working_proxy()
    dead_proxies = set()
    if proxy:
        dead_proxies.add(proxy)  # Sẽ không add vào trừ khi nó thực sự fail
        dead_proxies = set()     # Reset lại
    else:
        print("[!] Không lấy được proxy. Thử tải trực tiếp...")

    SKIP_TITLES = {'deleted video', 'private video', '[private video]', '[deleted video]'}

    for video in new_videos:
        vid_id = video['id']
        title = video['title']
        print(f"\n=========================================")
        print(f"[*] Đang xử lý: {title} ({vid_id})")

        if title.strip().lower() in SKIP_TITLES:
            print(f"[!] Bỏ qua: Video đã bị xóa hoặc ở chế độ riêng tư.")
            continue

        file_path, dead_proxies = download_video(vid_id, proxy, dead_proxies)

        # Cập nhật proxy còn sống để dùng cho video tiếp theo
        if dead_proxies:
            proxy = get_working_proxy(exclude=dead_proxies)

        if not file_path:
            print(f"[-] Bỏ qua video {vid_id} do lỗi tải.")
            continue

        try:
            desc = f"Backup từ video gốc: https://www.youtube.com/watch?v={vid_id}"
            new_id = upload_video_to_youtube(youtube, file_path, f"[BACKUP] {title}", desc)
            add_to_playlist(youtube, target_playlist_id, new_id)
            log_to_sheets(sheets_service, vid_id, new_id, title)
        except Exception as e:
            print(f"[-] Quá trình upload bị lỗi: {e}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                print(f"[*] Đã xóa file tạm {file_path}")

        time.sleep(10)

if __name__ == '__main__':
    main()
