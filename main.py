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
SKIP_TITLES = {'deleted video', 'private video', '[private video]', '[deleted video]'}

# ─────────────────────────────────────────────
#  AUTH & SERVICE
# ─────────────────────────────────────────────
def get_credentials():
    if not OAUTH_TOKEN_JSON:
        print("[!] Không tìm thấy GOOGLE_OAUTH_TOKEN trong biến môi trường.")
        sys.exit(1)
    creds = Credentials.from_authorized_user_info(json.loads(OAUTH_TOKEN_JSON))
    return creds

def get_youtube_service(creds):
    return build('youtube', 'v3', credentials=creds)

def get_sheets_service(creds):
    return build('sheets', 'v4', credentials=creds)

# ─────────────────────────────────────────────
#  SHEETS HELPERS
# ─────────────────────────────────────────────
def get_all_sheet_names(sheets_service):
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    metadata = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return {s['properties']['title']: s['properties']['sheetId']
            for s in metadata.get('sheets', [])}

def ensure_dashboard_sheet(sheets_service):
    """Tạo tab 'Dashboard' nếu chưa có, format header đẹp."""
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    sheets = get_all_sheet_names(sheets_service)

    if 'Dashboard' not in sheets:
        # Tạo tab mới
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": "Dashboard"}}}]}
        ).execute()
        print("[+] Đã tạo tab 'Dashboard'.")
        sheets = get_all_sheet_names(sheets_service)

    dash_sheet_id = sheets['Dashboard']

    # Ghi tiêu đề cột
    headers = [["Thống Kê", "Giá Trị"]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="'Dashboard'!A1:B1",
        valueInputOption="USER_ENTERED",
        body={"values": headers}
    ).execute()

    # Format header Dashboard
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": dash_sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": 2
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.22},
                        "horizontalAlignment": "CENTER",
                        "textFormat": {
                            "foregroundColor": {"red": 1.0, "green": 0.84, "blue": 0.0},
                            "bold": True,
                            "fontSize": 13
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        },
        # Độ rộng cột
        {
            "updateDimensionProperties": {
                "range": {"sheetId": dash_sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 260},
                "fields": "pixelSize"
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": dash_sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 180},
                "fields": "pixelSize"
            }
        }
    ]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests}
    ).execute()

    return dash_sheet_id

def update_dashboard(sheets_service, stats: dict):
    """Ghi toàn bộ thống kê lên tab Dashboard."""
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    dash_sheet_id = ensure_dashboard_sheet(sheets_service)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        ["📊 TỔNG QUAN KARAOKE BACKUP", ""],
        ["", ""],
        ["📅 Cập nhật lúc",                                    now],
        ["", ""],
        ["📋 Tổng video trong playlist nguồn",                  stats.get("total_source", 0)],
        ["✅ Tổng đã backup thành công (mọi lần)",              stats.get("total_backed_up", 0)],
        ["🆕 Video mới phát hiện lần này",                      stats.get("new_found", 0)],
        ["⬆️  Đã upload thành công lần này",                    stats.get("uploaded_this_run", 0)],
        ["⏭️  Bị bỏ qua (đã backup trước đó)",                 stats.get("skipped_duplicate", 0)],
        ["🗑️  Bị bỏ qua (video bị xóa/private)",               stats.get("skipped_deleted", 0)],
        ["❌ Thất bại lần này (lỗi proxy/tải)",                 stats.get("failed_this_run", 0)],
        ["", ""],
        ["📈 Tỉ lệ backup thành công (mọi lần)",               f"{stats.get('success_rate', 0)}%"],
    ]

    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="'Dashboard'!A1:B13",
        valueInputOption="USER_ENTERED",
        body={"values": rows}
    ).execute()

    # Format màu cho từng dòng data
    color_map = {
        0: (0.18, 0.18, 0.22),   # tiêu đề - tối
        1: (1, 1, 1),            # trống
        2: (0.93, 0.93, 0.98),   # Cập nhật lúc - xám nhạt
        3: (1, 1, 1),            # trống
        4: (0.86, 0.93, 1.0),    # Tổng nguồn - xanh nhạt
        5: (0.84, 0.97, 0.84),   # Đã backup - xanh lá nhạt
        6: (0.86, 0.93, 1.0),    # Video mới - xanh nhạt
        7: (0.76, 0.96, 0.80),   # Upload thành công - xanh lá
        8: (1.0, 0.97, 0.84),    # Bỏ qua trùng - vàng nhạt
        9: (1.0, 0.93, 0.84),    # Bỏ qua deleted - cam nhạt
        10: (1.0, 0.85, 0.85),   # Thất bại - đỏ nhạt
        11: (1, 1, 1),           # trống
        12: (0.84, 0.97, 0.84),  # Tỉ lệ - xanh lá nhạt
    }

    format_requests = []
    for row_idx, (r, g, b) in color_map.items():
        format_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": dash_sheet_id,
                    "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0, "endColumnIndex": 2
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": r, "green": g, "blue": b},
                        "textFormat": {
                            "bold": row_idx in (0, 12),
                            "fontSize": 13 if row_idx == 0 else 10
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        })

    # Merge tiêu đề to A1:B1
    format_requests.append({
        "mergeCells": {
            "range": {
                "sheetId": dash_sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 2
            },
            "mergeType": "MERGE_ALL"
        }
    })

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": format_requests}
    ).execute()

    print("[+] Đã cập nhật Dashboard!")

# ─────────────────────────────────────────────
#  SHEET LOG
# ─────────────────────────────────────────────
def read_processed_videos(sheets_service):
    """Đọc danh sách video ID đã backup từ Sheet log. Trả về set để kiểm tra O(1)."""
    print("[*] Đang đọc danh sách video đã backup từ Google Sheets...")
    try:
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        sheets = get_all_sheet_names(sheets_service)
        log_sheet = next(iter(sheets))  # Tab đầu tiên (Log)
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{log_sheet}'!A:A"
        ).execute()
        values = result.get('values', [])
        processed_ids = set()
        for row in values[1:]:   # Bỏ header
            if row:
                link = row[0]
                if "v=" in link:
                    vid_id = link.split("v=")[1].split("&")[0]
                    processed_ids.add(vid_id)
        print(f"[*] Đã backup trước đó: {len(processed_ids)} video.")
        return processed_ids
    except Exception as e:
        print(f"[-] Lỗi đọc Sheets: {e}")
        return set()

def log_to_sheets(sheets_service, original_id, new_id, title):
    print("[*] Ghi log vào Google Sheets...")
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    original_link = f"https://www.youtube.com/watch?v={original_id}"
    new_link = f"https://www.youtube.com/watch?v={new_id}"
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[original_link, new_link, title, date_str, "Thành công"]]
    sheets = get_all_sheet_names(sheets_service)
    log_sheet = next(iter(sheets))
    sheets_service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{log_sheet}'!A:E",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()
    print("[+] Đã ghi log thành công!")

# ─────────────────────────────────────────────
#  YOUTUBE HELPERS
# ─────────────────────────────────────────────
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
            videos.append({
                'id': item['snippet']['resourceId']['videoId'],
                'title': item['snippet']['title']
            })
        request = youtube.playlistItems().list_next(request, response)
    return videos

def download_video(video_id, proxy, dead_proxies):
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
            "--retries", "3",
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
            current_proxy = get_working_proxy(exclude=dead_proxies)
            if not current_proxy:
                print("  [!] Hết proxy sống để thử. Bỏ qua video này.")
                break

    return None, dead_proxies

def upload_video_to_youtube(youtube, file_path, title, description):
    print(f"[*] Bắt đầu upload file {file_path} lên YouTube...")
    body = {
        'snippet': {'title': title, 'description': description, 'categoryId': '10'},
        'status': {'privacyStatus': 'private'}
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
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
        body={"snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id}
        }}
    ).execute()
    print("[+] Đã thêm vào playlist!")

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
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

    # Đảm bảo tab Dashboard tồn tại
    ensure_dashboard_sheet(sheets_service)

    # Đọc lịch sử backup (dùng set để check trùng O(1))
    processed_ids = read_processed_videos(sheets_service)

    # Lấy toàn bộ video nguồn
    source_videos = []
    playlist_ids = [pid.strip() for pid in source_playlist_ids.split(",") if pid.strip()]
    for pid in playlist_ids:
        source_videos.extend(get_playlist_videos(youtube, pid))

    total_source = len(source_videos)
    skipped_duplicate = 0
    skipped_deleted = 0
    uploaded_this_run = 0
    failed_this_run = 0

    # Lọc video mới, tách video bị xóa/private khỏi luồng chính
    new_videos = []
    for v in source_videos:
        if v['id'] in processed_ids:
            skipped_duplicate += 1
        elif v['title'].strip().lower() in SKIP_TITLES:
            skipped_deleted += 1
        else:
            new_videos.append(v)

    new_found = len(new_videos)
    print(f"\n[*] Tổng playlist nguồn   : {total_source} video")
    print(f"[*] Đã backup trước đó    : {len(processed_ids)} video ({skipped_duplicate} trùng trong nguồn)")
    print(f"[*] Đã xóa/private        : {skipped_deleted} video (bỏ qua)")
    print(f"[*] Cần backup lần này    : {new_found} video\n")

    if not new_videos:
        print("[*] Không có video nào mới. Cập nhật Dashboard và kết thúc.")
        total_backed_up = len(processed_ids)
        success_rate = round(total_backed_up / total_source * 100, 1) if total_source else 0
        update_dashboard(sheets_service, {
            "total_source": total_source,
            "total_backed_up": total_backed_up,
            "new_found": 0,
            "uploaded_this_run": 0,
            "skipped_duplicate": skipped_duplicate,
            "skipped_deleted": skipped_deleted,
            "failed_this_run": 0,
            "success_rate": success_rate,
        })
        return

    # Proxy
    proxy = get_working_proxy()
    dead_proxies = set()
    if not proxy:
        print("[!] Không lấy được proxy. Thử tải trực tiếp...")

    for video in new_videos:
        vid_id = video['id']
        title = video['title']
        print(f"\n=========================================")
        print(f"[*] Đang xử lý: {title} ({vid_id})")

        file_path, dead_proxies = download_video(vid_id, proxy, dead_proxies)
        if dead_proxies:
            proxy = get_working_proxy(exclude=dead_proxies)

        if not file_path:
            print(f"[-] Bỏ qua video {vid_id} do lỗi tải.")
            failed_this_run += 1
            continue

        try:
            desc = f"Backup từ video gốc: https://www.youtube.com/watch?v={vid_id}"
            new_id = upload_video_to_youtube(youtube, file_path, f"[BACKUP] {title}", desc)
            add_to_playlist(youtube, target_playlist_id, new_id)
            log_to_sheets(sheets_service, vid_id, new_id, title)
            uploaded_this_run += 1
            processed_ids.add(vid_id)   # Cập nhật local set để tránh trùng trong cùng session
        except Exception as e:
            print(f"[-] Quá trình upload bị lỗi: {e}")
            failed_this_run += 1
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                print(f"[*] Đã xóa file tạm {file_path}")

        time.sleep(10)

    # Cập nhật Dashboard sau khi chạy xong
    total_backed_up = len(processed_ids)
    success_rate = round(total_backed_up / total_source * 100, 1) if total_source else 0
    update_dashboard(sheets_service, {
        "total_source": total_source,
        "total_backed_up": total_backed_up,
        "new_found": new_found,
        "uploaded_this_run": uploaded_this_run,
        "skipped_duplicate": skipped_duplicate,
        "skipped_deleted": skipped_deleted,
        "failed_this_run": failed_this_run,
        "success_rate": success_rate,
    })

    print(f"\n========================================= KẾT THÚC")
    print(f"  Upload thành công : {uploaded_this_run}")
    print(f"  Thất bại          : {failed_this_run}")
    print(f"  Tổng đã backup    : {total_backed_up}/{total_source} ({success_rate}%)")

if __name__ == '__main__':
    main()
