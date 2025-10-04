# scripts/test_dex.py
import requests
import time
MINT = "So11111111111111111111111111111111111111112"
t0 = time.time()
r = requests.get(
    f"https://api.dexscreener.com/latest/dex/tokens/{MINT}", timeout=10)
print("HTTP", r.status_code, "in", round(time.time()-t0, 2), "s")
print("keys:", list(r.json().keys()))
