# scripts/test_post.py
import json
import requests
import time
from core.config import DISCORD_WEBHOOK, DRY_RUN

embed = {
    "title": "FreshBot webhook test",
    "description": "If you see this in Discord, the webhook is OK.",
    "color": 5814783,
    "fields": [{"name": "Time", "value": time.strftime("%Y-%m-%d %H:%M:%S")}]
}

if DRY_RUN or not DISCORD_WEBHOOK:
    print("[DRY] Would post:", json.dumps(embed, indent=2))
else:
    r = requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=15)
    r.raise_for_status()
    print("Posted OK")
