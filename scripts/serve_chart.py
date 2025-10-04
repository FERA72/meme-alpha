# scripts/serve_chart.py  — Real-time candlestick viewer with B/S markers
# Run:  python scripts/serve_chart.py  → http://localhost:8765/?mint=<MINT>
import json
import time
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

DEX_TOKENS_V1 = "https://api.dexscreener.com/tokens/v1/{chainId}/{tokenAddresses}"

HTML = """<!doctype html><html><head>
<meta charset="utf-8"/><title>Bot Chart (Candles, Live)</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<style>
  :root{--bg:#0b0f14;--panel:#0f141b;--text:#e6edf3;--muted:#9fb5c6;--accent:#19c37d;--red:#ff6b6b;--grid:#13202c}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,Segoe UI,Roboto,Arial}
  .wrap{max-width:1200px;margin:24px auto;padding:0 16px}
  header{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .pill{background:#0e1b24;border:1px solid #183041;color:#b9d3e4;padding:4px 8px;border-radius:999px;font-size:12px}
  .card{background:var(--panel);border:1px solid #14212c;border-radius:14px;padding:12px}
  h1{font-size:18px;margin:0}
  a{color:#7cc6ff;text-decoration:none}
  #chart{height:60vh}
  .legend{font-size:12px;color:var(--muted);margin-top:8px}
  .row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  .spacer{flex:1}
  select{background:#0f1a23;border:1px solid #1b3241;color:#c7d6e2;padding:6px 8px;border-radius:8px}
</style>
</head><body>
<div class="wrap">
  <header class="row">
    <h1>Bot Candles <span id="sym" class="pill"></span></h1>
    <span id="mintPill" class="pill"></span>
    <a id="pair" class="pill" target="_blank" rel="noopener">Open pair ↗</a>
    <span id="status" class="pill">connecting…</span>
    <div class="spacer"></div>
    <label>Timeframe</label>
    <select id="tf">
      <option value="5000">5s</option>
      <option value="15000">15s</option>
      <option value="60000" selected>1m</option>
      <option value="300000">5m</option>
    </select>
  </header>

  <div class="card">
    <div id="chart"><canvas id="c"></canvas></div>
    <div class="legend">B/S markers from a simple EMA cross + momentum + DD stop. Viz only.</div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@3.3.0/dist/chartjs-chart-financial.min.js"></script>
<script>
const q = new URLSearchParams(location.search);
const mint = q.get("mint") || "";
document.getElementById('mintPill').textContent = mint ? (mint.slice(0,6)+"…"+mint.slice(-4)) : '';
let meta = {symbol:null, pair_url:null};
let samples = []; // {t, price}
let candles = []; // {t,o,h,l,c}
let bs = [];      // {x,y,type:'BUY'|'SELL'}
let entry = null;
let tfMs = 60000;

function ema(values, period){ const k=2/(period+1); let out=[],prev=values[0]??0;
  for(let i=0;i<values.length;i++){ const v=values[i]; prev=i===0?v:(v-prev)*k+prev; out.push(prev);} return out; }
function pct(a,b){ if(!b) return 0; return (a-b)/b*100; }

function strategyOnClose(){
  if(candles.length < 25) return;
  const closes = candles.map(c=>c.c);
  const ema8 = ema(closes,8), ema21 = ema(closes,21);
  const i = closes.length-1;
  const mom8 = pct(closes[i], closes[Math.max(0,i-8)]);
  const dd = entry ? pct(closes[i], entry.price) : 0;
  const crossUp = ema8[i] > ema21[i] && ema8[i-1] <= ema21[i-1];
  if(!entry && crossUp && mom8 > 1.5){
    entry = {idx:i, price:closes[i]};
    bs.push({x:candles[i].t, y:closes[i], type:'BUY'});
    return;
  }
  const crossDn = ema8[i] < ema21[i] && ema8[i-1] >= ema21[i-1];
  if(entry && (dd < -12 || crossDn || mom8 < -1)){
    bs.push({x:candles[i].t, y:closes[i], type:'SELL'});
    entry = null;
  }
}

function rebuildCandles(){
  if(!samples.length) return;
  const tf = tfMs;
  const firstBucket = Math.floor(samples[0].t/tf)*tf;
  let bucketStart = firstBucket, i=0, out=[];
  while(i < samples.length){
    let o=null,h=-Infinity,l=Infinity,c=null,ts=bucketStart;
    while(i<samples.length && Math.floor(samples[i].t/tf)*tf===bucketStart){
      const p=samples[i].price; if(o===null) o=p; h=Math.max(h,p); l=Math.min(l,p); c=p; i++;
    }
    if(o===null){ bucketStart += tf; continue; }
    out.push({t:ts,o,h,l,c}); bucketStart += tf;
  }
  candles = out.slice(-720);
  strategyOnClose();
  render();
}

async function poll(){
  if(!mint) return;
  try{
    const r = await fetch('/api/live?mint='+encodeURIComponent(mint));
    const j = await r.json();
    if(j.error) throw new Error(j.error);
    if(!meta.symbol && j.symbol){ meta.symbol=j.symbol; document.getElementById('sym').textContent=j.symbol||'—'; }
    if(!meta.pair_url && j.pair_url){ meta.pair_url=j.pair_url; const p=document.getElementById('pair'); p.href=j.pair_url; }
    const t=j.ts, price=parseFloat(j.priceUsd);
    if(Number.isFinite(price)){
      samples.push({t,price});
      const cutoff=t-(6*60*60*1000); while(samples.length && samples[0].t<cutoff) samples.shift();
      rebuildCandles();
    }
    document.getElementById('status').textContent = 'live @ '+new Date(t).toLocaleTimeString();
  }catch(e){
    document.getElementById('status').textContent='disconnected';
  }
}

let chart;
function render(){
  if(!chart){
    const ctx=document.getElementById('c').getContext('2d');
    chart = new Chart(ctx,{type:'candlestick',data:{datasets:[
      {label:'Price (USD)',data:candles.map(c=>({x:c.t,o:c.o,h:c.h,l:c.l,c:c.c})),yAxisID:'y'},
      {label:'Signals',type:'scatter',data:bs,parsing:false,yAxisID:'y',
       pointRadius:5,pointBackgroundColor:(ctx)=>ctx.raw?.type==='BUY'?'#19c37d':'#ff6b6b',pointBorderColor:'#0b0f14'}
    ]},options:{animation:false,maintainAspectRatio:false,
      scales:{x:{type:'time',grid:{color:'var(--grid)'},ticks:{color:'#86a3b6'}},
              y:{position:'left',grid:{color:'var(--grid)'},ticks:{color:'#b4d0e5'}}},
      plugins:{legend:{labels:{color:'#b4d0e5'}}}}); }
  else{
    chart.data.datasets[0].data = candles.map(c=>({x:c.t,o:c.o,h:c.h,l:c.l,c:c.c}));
    chart.data.datasets[1].data = bs; chart.update();
  }
}

setInterval(poll, 3000);
document.getElementById('tf').addEventListener('change', e=>{ tfMs=parseInt(e.target.value,10); rebuildCandles(); });
</script></body></html>
"""


def best_pair(pairs):
    if not pairs:
        return None

    def key(p):
        liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
        quote = (p.get("quoteToken") or {}).get("symbol", "")
        prio = 1 if quote in ("USDC", "USDT", "USD") else 0
        return (prio, liq)
    return sorted(pairs, key=key, reverse=True)[0]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): return

    def _send(self, code, body, ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            if u.path == "/":
                return self._send(200, HTML.encode(), "text/html")
            if u.path == "/health":
                return self._send(200, b"ok", "text/plain")
            if u.path == "/api/live":
                qs = parse_qs(u.query)
                mint = (qs.get("mint") or [""])[0].strip()
                chain = (qs.get("chain") or ["solana"])[
                    0].strip().lower() or "solana"
                if not mint:
                    return self._send(400, json.dumps({"error": "mint required"}).encode(), "application/json")
                url = DEX_TOKENS_V1.format(chainId=chain, tokenAddresses=mint)
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                pairs = data if isinstance(data, list) else data.get(
                    "pairs") or data.get("data") or []
                p = best_pair(pairs)
                if not p:
                    return self._send(404, json.dumps({"error": "pair not found"}).encode(), "application/json")
                payload = {
                    "chainId": p.get("chainId"),
                    "pairAddress": p.get("pairAddress"),
                    "dexId": p.get("dexId"),
                    "pair_url": p.get("url"),
                    "symbol": (p.get("baseToken") or {}).get("symbol"),
                    "priceUsd": p.get("priceUsd"),
                    "txns": p.get("txns", {}),
                    "volume": p.get("volume", {}),
                    "liquidity": p.get("liquidity", {}),
                    "ts": int(time.time()*1000)
                }
                return self._send(200, json.dumps(payload).encode(), "application/json")
            return self._send(404, b"not found", "text/plain")
        except Exception as e:
            return self._send(500, json.dumps({"error": repr(e)}).encode(), "application/json")


def main(port=8765):
    print(f"[viewer] http://localhost:{port}/?mint=<MINT>")
    HTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    main()
