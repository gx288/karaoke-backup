import subprocess
import os
import json
from proxy_manager import get_working_proxy

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLZC4gKOl6VcPQ3fK-mWst_X7SarnU-rj_"

def main():
    print("=== CHẠY THỬ NGHIỆM LOCAL: DOWNLOAD VIDEO QUA PROXY ===")
    
    # Do playlist có thể là Private hoặc bị YouTube block yt-dlp, ta lấy cứng 1 video test
    vid_id = "jNQXAC9IVRw" # Me at the zoo (hoặc bất kỳ video nào)
    title = "Me at the zoo"
    
    print(f"\n[*] Sẽ thử tải video ĐẦU TIÊN: {title} ({vid_id})")
    
    # 2. Tìm proxy sống
    proxy = get_working_proxy()
    if proxy:
        print(f"[*] Bắt đầu tải với proxy: {proxy}")
    else:
        print("[!] Không có proxy sống, thử tải trực tiếp...")

    # 3. Tải video
    url = f"https://www.youtube.com/watch?v={vid_id}"
    out_tmpl = f"TEST_{vid_id}.mp4"
    
    cmd_dl = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        url
    ]
    
    if proxy:
        cmd_dl.extend(["--proxy", proxy])
        
    try:
        subprocess.run(cmd_dl, check=True)
        if os.path.exists(out_tmpl):
            print(f"\n[+] THÀNH CÔNG! Đã tải file {out_tmpl} (Dung lượng: {os.path.getsize(out_tmpl) // 1024} KB)")
        else:
            print("[-] File không tồn tại sau khi tải.")
    except subprocess.CalledProcessError as e:
        print(f"[-] Lỗi tải video: {e}")

if __name__ == '__main__':
    main()
