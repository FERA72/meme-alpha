# scripts/test_helius.py
import requests
import json
from core.config import HELIUS_RPC
from core.helius import get_recent_signatures

print("RPC:", HELIUS_RPC)
health = requests.post(HELIUS_RPC, json={
                       "jsonrpc": "2.0", "id": 1, "method": "getHealth", "params": []}, timeout=15)
print("Health:", health.status_code, health.text)

sigs = get_recent_signatures(limit=10)
print("Recent Raydium sigs:", len(sigs))
print("Sample:", [s["signature"] for s in sigs[:3]])
