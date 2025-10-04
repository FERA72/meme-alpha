# core/helius.py (only the key bits shown)
import requests
from core.config import HELIUS_RPC, RAYDIUM_AMM_V4

DEFAULT_TIMEOUT = 15
_session = requests.Session()


def _post(payload):
    r = _session.post(HELIUS_RPC, json=payload, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Helius RPC error: {data['error']}")
    if "result" not in data:
        raise RuntimeError(f"Helius RPC missing 'result': {data}")
    return data["result"]


def get_recent_signatures(limit=60, before=None):
    params = [RAYDIUM_AMM_V4, {"limit": int(limit)}]
    if before:
        params[1]["before"] = before
    return _post({"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": params})
