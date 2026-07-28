import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from curl_cffi import requests
except ImportError:
    import sys
    print("[!] Cần cài đặt curl_cffi: pip install curl_cffi")
    sys.exit(1)

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# Sử dụng endpoint cực nhẹ của YouTube để test ping
TEST_URL = "https://www.youtube.com/generate_204"

def fetch_all_proxies():
    print("=== BƯỚC 1: THU THẬP PROXY ===")
    all_proxies = set()
    for url in PROXY_SOURCES:
        try:
            proto = "socks5" if "socks5" in url.lower() else "http"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                lines = r.text.split("\n")
                count = 0
                for line in lines:
                    line = line.strip()
                    if line and ":" in line and not line.startswith("#"):
                        parts = line.split(":")
                        if len(parts) == 2:
                            all_proxies.add(f"{proto}://{line}")
                            count += 1
                print(f"  [+] Đã lấy {count} proxy từ {url.split('/')[-1]}")
        except Exception as e:
            print(f"  [-] Lỗi tải từ {url}: {e}")
    print(f"[*] Tổng số proxy thu thập được: {len(all_proxies)}")
    return list(all_proxies)

def test_proxy(proxy_url):
    proxies = {"http": proxy_url, "https": proxy_url}
    start_time = time.time()
    try:
        # Gọi thử lên YouTube
        r = requests.get(TEST_URL, headers=HEADERS, impersonate="chrome120", proxies=proxies, timeout=10)
        # generate_204 trả về 204 No Content nếu kết nối thành công
        if r.status_code == 204 or r.status_code == 200:
            return proxy_url, time.time() - start_time
    except Exception:
        pass
    return None

def get_working_proxy():
    """Hàm dành cho main.py gọi để lấy ra 1 proxy sống"""
    candidates = fetch_all_proxies()
    if not candidates:
        return None
        
    random.shuffle(candidates)
    # Rút gọn số lượng test để tiết kiệm thời gian (khoảng 300 proxy)
    to_test = candidates[:300]
    
    print(f"\n=== BƯỚC 2: KIỂM TRA PROXY CHO YOUTUBE ===")
    
    executor = ThreadPoolExecutor(max_workers=50)
    try:
        futures = {executor.submit(test_proxy, p): p for p in to_test}
        for future in as_completed(futures):
            res = future.result()
            if res:
                print(f"  [+] Proxy ngon: {res[0]} (Ping: {res[1]:.2f}s)")
                # Chỉ cần 1 proxy sống là đủ trả về
                executor.shutdown(wait=False, cancel_futures=True)
                return res[0]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    print("[!] Không tìm thấy proxy nào sống trong mẻ này.")
    return None

if __name__ == "__main__":
    p = get_working_proxy()
    if p:
        print(f"Proxy tìm được: {p}")
