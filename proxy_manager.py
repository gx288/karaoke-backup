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

TEST_URL = "https://www.youtube.com/generate_204"

# Cache toàn bộ proxy đã scrape trong session này để không phải fetch lại
_ALL_PROXIES_CACHE = None

def fetch_all_proxies():
    global _ALL_PROXIES_CACHE
    if _ALL_PROXIES_CACHE is not None:
        return _ALL_PROXIES_CACHE

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
    _ALL_PROXIES_CACHE = list(all_proxies)
    return _ALL_PROXIES_CACHE

def test_proxy(proxy_url):
    proxies = {"http": proxy_url, "https": proxy_url}
    start_time = time.time()
    try:
        r = requests.get(TEST_URL, headers=HEADERS, impersonate="chrome120", proxies=proxies, timeout=10)
        if r.status_code == 204 or r.status_code == 200:
            return proxy_url, time.time() - start_time
    except Exception:
        pass
    return None

def get_working_proxy(exclude=None):
    """
    Lấy 1 proxy sống để dùng cho yt-dlp.
    Tham số `exclude`: set các proxy đã hỏng để tránh lấy lại.
    """
    if exclude is None:
        exclude = set()

    candidates = fetch_all_proxies()
    if not candidates:
        return None

    # Lọc bỏ các proxy đã biết hỏng
    candidates = [p for p in candidates if p not in exclude]
    if not candidates:
        print("[!] Đã thử hết tất cả proxy khả dụng.")
        return None

    random.shuffle(candidates)
    # Test 300 proxy ngẫu nhiên để tìm ra 1 con sống
    to_test = candidates[:300]

    print(f"\n=== KIỂM TRA PROXY ({len(to_test)} proxy, bỏ qua {len(exclude)} proxy hỏng) ===")

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(test_proxy, p): p for p in to_test}
        for future in as_completed(futures):
            res = future.result()
            if res:
                print(f"  [+] Proxy ngon: {res[0]} (Ping: {res[1]:.2f}s)")
                executor.shutdown(wait=False, cancel_futures=True)
                return res[0]

    print("[!] Không tìm thấy proxy nào sống trong mẻ này.")
    return None

if __name__ == "__main__":
    p = get_working_proxy()
    if p:
        print(f"Proxy tìm được: {p}")
