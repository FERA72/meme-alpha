# scripts/serve_chart.py
import requests
import json
import os
import sqlite3
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 8765
DB_PATH = "freshbot.sqlite3"

HTML = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Mint viewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    html,body,#wrap {{ height:100%; margin:0; background:#0b1220; color:#e6edf3; font-family:ui-sans-serif,system-ui }}
    #hdr {{ padding:10px 14px; border-bottom:1px solid #1e2636; display:flex; gap:10px; align-items:center }}
    #sym {{ font-weight:600 }}
    #chart {{ height: calc(100% - 52px); }}
    a {{ color:#8ab4ff; text-decoration:none }}
    .tag {{ background:#1b2233; padding:4px 8px; border-radius:8px; font-size:12px }}
  </style>
  <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
  <div id="wrap">
    <div id="hdr">
      <div id="sym"></div>
      <span class="tag" id="mint"></span>
      <a id="dslink" class="tag" target="_blank" rel="noreferrer">Dex page</a>
      <span class="tag" id="status">loading…</span>
    </div>
    <div id="chart"></div>
  </div>
  <script>
    const qs = new URLSearchParams(location.search);
    const MINT = qs.get('mint') || '';
    document.getElementById('mint').textContent = MINT || 'unknown';

    const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
      layout: {{ background: {{ type:'solid', color:'#0b1220' }}, textColor:'#e6edf3' }},
      grid: {{ vertLines: {{ color:'#1e2636' }}, horzLines: {{ color:'#1e2636' }} }},
      timeScale: {{ rightOffset: 2, secondsVisible: true }},
      crosshair: {{ mode: 0 }}
    }});
    const candleSeries = chart.addCandlestickSeries();
    const buyMarkers = []; const sellMarkers = [];

    function setStatus(t) {{ document.getElementById('status').textContent = t }}

    async function fetchDexCandles(mint) {{
      // Use DexScreener's public token endpoint to find a liquid pair, then fetch chart data via proxy /candles
      // We read through the server to avoid CORS headaches; the server exposes /candles for us.
      const r = await fetch('/candles?mint=' + encodeURIComponent(mint));
      if (!r.ok) throw new Error('candle fetch failed');
      return await r.json(); // {{ candles:[{{time,open,high,low,close}}], symbol, pairUrl }}
    }}

    async function fetchServerSignals(mint) {{
      const r = await fetch('/api/live?mint=' + encodeURIComponent(mint));
      if (!r.ok) return {{ signals: [] }};
      return await r.json();
    }}

    function drawMarkersFromServer(sigs) {{
      const m = [];
      for (const s of sigs) {{
        const time = Math.floor(new Date(s.t).getTime() / 1000);
        const text = s.side === 'B' ? 'B' : 'S';
        const color = s.side === 'B' ? '#00e676' : '#ff6e6e';
        m.push({{ time, position: s.side === 'B' ? 'belowBar' : 'aboveBar', shape:'circle', color, text, size:1 }});
      }}
      candleSeries.setMarkers(m);
    }}

    async function bootstrap() {{
      if (!MINT) {{ setStatus('no mint'); return; }}
      try {{
        const boot = await fetchDexCandles(MINT);
        document.getElementById('sym').textContent = boot.symbol || 'Pair';
        document.getElementById('dslink').href = boot.pairUrl || '#';
        candleSeries.setData(boot.candles);
        setStatus('live');
        refreshSignals();
        refreshCandles();  // light refresh to extend candles
      }} catch(e) {{
        setStatus('error: ' + e.message);
      }}
    }}

    async function refreshCandles() {{
      try {{
        const boot = await fetchDexCandles(MINT);
        candleSeries.setData(boot.candles);
      }} catch(e) {{}}
      setTimeout(refreshCandles, 8000);
    }}

    async function refreshSignals() {{
      try {{
        const j = await fetchServerSignals(MINT);
        drawMarkersFromServer(j.signals || []);
      }} catch(e) {{}}
      setTimeout(refreshSignals, 5000);
    }}

    bootstrap();
  </script>
</body>
</html>"""


def _conn():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS ai_trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      mint TEXT NOT NULL,
      ts   TEXT NOT NULL,
      side TEXT NOT NULL CHECK(side IN ('B','S')),
      price REAL NOT NULL,
      conf REAL,
      UNIQUE(mint, ts, side)
    );""")
    return con


def _json(obj, code=200):
    b = json.dumps(obj).encode()
    return code, {"Content-Type": "application/json", "Content-Length": str(len(b))}, b


def _html(s, code=200):
    b = s.encode()
    return code, {"Content-Type": "text/html", "Content-Length": str(len(b))}, b


def _bad(msg="bad request", code=400):
    return _json({"error": msg}, code)


# Very small DexScreener proxy so the page can load candles without CORS pain


def proxy_candles(mint: str):
    # find top pair for the mint
    j = requests.get(
        f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=10).json()
    pairs = (j or {}).get("pairs") or []
    if not pairs:
        return {"candles": [], "symbol": "unknown", "pairUrl": None}
    pair = max(pairs, key=lambda p: float(
        p.get("liquidity", {}).get("usd", 0) or 0))
    symbol = f"{pair.get('baseToken', {}).get('symbol', '?')}/{pair.get('quoteToken', {}).get('symbol', '?')}"
    pair_url = pair.get("url")
    # DexScreener bars endpoint (1m). If unavailable just synthesize from last trades.
    # Public bars API:
    #   https://api.dexscreener.com/chart/bars/{chain}/{pairAddress}?from=unix&to=unix&resolution=1
    chain = pair.get("chainId") or "solana"
    addr = pair.get("pairAddress")
    now = int(time.time())
    frm = now - 60*60*6   # ~6h
    bars = requests.get(
        f"https://api.dexscreener.com/chart/bars/{chain}/{addr}",
        params={"from": frm, "to": now, "resolution": 1}, timeout=10
    ).json()
    candles = []
    for b in (bars or []):
        # each bar: [t, o, h, l, c, v] per docs; time is unix seconds
        try:
            candles.append({"time": int(b[0]), "open": float(b[1]), "high": float(b[2]),
                            "low": float(b[3]), "close": float(b[4])})
        except Exception:
            continue
    return {"candles": candles[-800:], "symbol": symbol, "pairUrl": pair_url}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                code, headers, body = _html(HTML)
            elif u.path == "/health":
                code, headers, body = _html("ok")
            elif u.path == "/api/live":
                qs = parse_qs(u.query)
                mint = (qs.get("mint", [""])[0] or "").strip()
                if not mint:
                    code, headers, body = _bad("missing mint")
                    self._send(code, headers, body)
                    return
                con = _conn()
                cur = con.cursor()
                cur.execute(
                    "SELECT ts, side, price, conf FROM ai_trades WHERE mint=? ORDER BY ts ASC LIMIT 500", (mint,))
                rows = cur.fetchall()
                con.close()
                code, headers, body = _json({"signals": [{"t": r[0], "side": r[1], "price": float(
                    r[2]), "conf": (r[3] if r[3] is not None else None)} for r in rows]})
            elif u.path == "/candles":
                qs = parse_qs(u.query)
                mint = (qs.get("mint", [""])[0] or "").strip()
                if not mint:
                    code, headers, body = _bad("missing mint")
                    self._send(code, headers, body)
                    return
                data = proxy_candles(mint)
                code, headers, body = _json(data)
            elif u.path == "/api/marker/test":
                # quick manual test: /api/marker/test?mint=<MINT>
                qs = parse_qs(u.query)
                mint = (qs.get("mint", [""])[0] or "").strip()
                if not mint:
                    code, headers, body = _bad("missing mint")
                    self._send(code, headers, body)
                    return
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                con = _conn()
                con.execute("INSERT OR IGNORE INTO ai_trades(mint, ts, side, price, conf) VALUES(?,?,?,?,?)",
                            (mint, ts, "B", 1.0, 0.66))
                con.execute("INSERT OR IGNORE INTO ai_trades(mint, ts, side, price, conf) VALUES(?,?,?,?,?)",
                            (mint, ts, "S", 1.0, 0.55))
                con.commit()
                con.close()
                code, headers, body = _json({"ok": True})
            else:
                code, headers, body = _bad("not found", 404)
            self._send(code, headers, body)
        except Exception as e:
            code, headers, body = _bad(f"server error: {e}", 500)
            try:
                self._send(code, headers, body)
            except:
                pass

    def log_request(self, *args, **kwargs):
        # keep console clean
        pass

    def _send(self, code, headers, body):
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


def main():
    print(f"[viewer] http://localhost:{PORT}/?mint=<MINT>")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
