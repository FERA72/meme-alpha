# core/config.py
import os
import re
from pathlib import Path

# --- load .env quietly ---


def _load_env():
    for p in (Path(__file__).resolve().parents[1] / ".env", Path(".env")):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line or line.strip().startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ---- helpers ----
_BASE58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _clean_pubkey(s: str) -> str:
    # remove ANY non-base58 char (kills zero-width, BOM, whitespace, etc.)
    return "".join(ch for ch in (s or "") if ch in _BASE58)


def _get_str(name, default=""):
    return os.getenv(name, default).strip()


def _get_num(name, default, kind=float):
    raw = os.getenv(name, str(default))
    raw = raw.split("#", 1)[0].strip()   # allow inline comments in .env safely
    m = re.search(r"-?\d+(\.\d+)?", raw)
    return kind(m.group()) if m else kind(default)


# ---- creds / runtime ----
HELIUS_API_KEY = _get_str("HELIUS_API_KEY")
DISCORD_WEBHOOK = _get_str("DISCORD_WEBHOOK")
DRY_RUN = (_get_str("DRY_RUN", "1") == "1")
POLL_SECONDS = int(_get_num("POLL_SECONDS", 20, int))
CHART_BASE_URL = _get_str("CHART_BASE_URL") or "http://localhost:8765"
HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# ---- thresholds used by filters/scoring ----
MAX_AGE_MIN = float(_get_num("MAX_AGE_MIN",   8, float))
MIN_LIQ_USD = float(_get_num("MIN_LIQ_USD",   15000, float))
MIN_MCAP_USD = float(_get_num("MIN_MCAP_USD",  100000, float))
FDV_LIQ_MAX = float(_get_num("FDV_LIQ_MAX",   80, float))
MIN_SCORE = float(_get_num("MIN_SCORE",     70, float))
SCORE_REPOST_BUMP = float(_get_num("SCORE_REPOST_BUMP", 10, float))
FRESH_GRACE_MIN = float(_get_num("FRESH_GRACE_MIN",    2, float))
FRESH_LIQ_FACTOR = float(_get_num("FRESH_LIQ_FACTOR",   0.7, float))
SUPER_FRESH_MIN = float(_get_num("SUPER_FRESH_MIN",    1, float))
SUPER_FRESH_FACTOR = float(_get_num("SUPER_FRESH_FACTOR", 0.5, float))

# ---- Raydium AMM v4 program id (sanitize the LITERAL itself) ----
# This raw string might contain an invisible char if it was pasted badly.
_RAYDIUM_CANON_RAW = "675kPX9MHTj52zt1qfrf1NVHuzelxFQ9MH24wFSUt1Mp8"
_RAYDIUM_CANON = _clean_pubkey(_RAYDIUM_CANON_RAW)

# By default we IGNORE env to avoid broken overrides. Opt-in with USE_ENV_RAYDIUM=1
USE_ENV_RAYDIUM = _get_str("USE_ENV_RAYDIUM") == "1"
if USE_ENV_RAYDIUM:
    _env_raw = _get_str("RAYDIUM_AMM_V4")
    _env_clean = _clean_pubkey(_env_raw)
    RAYDIUM_AMM_V4 = _env_clean if len(_env_clean) == 44 else _RAYDIUM_CANON
else:
    RAYDIUM_AMM_V4 = _RAYDIUM_CANON

# soft warnings
if len(RAYDIUM_AMM_V4) != 44:
    print(
        f"[Config] WARN: RAYDIUM_AMM_V4 len={len(RAYDIUM_AMM_V4)} -> {RAYDIUM_AMM_V4!r}")
if not HELIUS_API_KEY:
    print("[Config] WARN: HELIUS_API_KEY missing (set it in .env).")
