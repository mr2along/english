import os
import time
from urllib.parse import quote
import requests

USER = os.getenv("WEBSHARE_USERNAME", "").strip()
PASSWORD = os.getenv("WEBSHARE_PASSWORD", "").strip()
HOST = os.getenv("WEBSHARE_PROXY_HOST", "p.webshare.io").strip()
PORT = os.getenv("WEBSHARE_PROXY_PORT", "80").strip()
TIMEOUT = int(os.getenv("PROXY_TEST_TIMEOUT", "15"))

if not all([USER, PASSWORD, HOST, PORT]):
    print("[DIAG] Missing Webshare configuration", flush=True)
else:
    proxy = f"http://{quote(USER, safe='')}:{quote(PASSWORD, safe='')}@{HOST}:{PORT}/"
    proxies = {"http": proxy, "https": proxy}
    print(f"[DIAG] Webshare endpoint: {HOST}:{PORT}", flush=True)
    for name, url in [
        ("webshare-ip", "https://ipv4.webshare.io/"),
        ("google", "https://www.google.com/generate_204"),
        ("youtube-home", "https://www.youtube.com/"),
        ("youtube-video", "https://www.youtube.com/watch?v=vxtvWovNKKE"),
    ]:
        started = time.time()
        try:
            r = requests.get(url, proxies=proxies, timeout=TIMEOUT, allow_redirects=True)
            print(f"[DIAG] {name}: OK status={r.status_code} elapsed={time.time()-started:.2f}s final={r.url}", flush=True)
        except Exception as exc:
            print(f"[DIAG] {name}: FAIL {type(exc).__name__}: {exc} elapsed={time.time()-started:.2f}s", flush=True)
