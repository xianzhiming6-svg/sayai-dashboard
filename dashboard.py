#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
说AI懂的话 - 监控仪表盘后端
一个文件：接收用量上报 + 返回Q版仪表盘HTML
"""
import sqlite3, json, time, os, urllib.request, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DB = os.path.join(os.path.dirname(__file__), "usage.db")
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_URL = "https://api.deepseek.com/v1/chat/completions"

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            install_id TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            cost_yuan REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )''')

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/report":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            with sqlite3.connect(DB) as c:
                c.execute("INSERT INTO usage_logs (install_id,tokens,cost_yuan) VALUES (?,?,?)",
                    (data.get("install_id",""), data.get("tokens",0), data.get("cost_yuan",0)))
            self.send_response(200); self.end_headers()
            self.wfile.write(b"ok")
        elif self.path == "/translate":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            result = self._call_deepseek(data.get("messages", []), data.get("model", "deepseek-v4-flash"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        elif self.path == "/activate":
            LIC = os.environ.get("LICENSE_SECRET", "sayai_2026_secret_key_xzm")
            cl = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(cl)) if cl else {}
            iid = data.get("install_id", "")
            code = data.get("code", "")
            expected = hashlib.sha256((iid + LIC).encode()).hexdigest()[:16]
            ok = (code == expected)
            expires = ""
            if ok:
                import time as _t
                expires = _t.strftime("%Y-%m-%d", _t.localtime(_t.time() + 30*86400))
                with sqlite3.connect(DB) as c:
                    c.execute("CREATE TABLE IF NOT EXISTS activations (install_id TEXT PRIMARY KEY, activated_at TEXT, expires_at TEXT)")
                    c.execute("INSERT OR REPLACE INTO activations VALUES (?,?,?)", (iid, _t.strftime("%Y-%m-%d"), expires))
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
            self.wfile.write(json.dumps({"ok":ok,"expires":expires}).encode())
        else:
            self.send_response(404); self.end_headers()

    def _call_deepseek(self, messages, model):
        if not DS_KEY: return {"error": "未配置 DEEPSEEK_API_KEY"}
        try:
            data = json.dumps({"model": model, "messages": messages,
                "max_tokens": 900, "temperature": 0.3,
                "thinking": {"type": "disabled"}}).encode()
            req = urllib.request.Request(DS_URL, data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_KEY}"})
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
            tokens = resp.get("usage", {}).get("total_tokens", 0)
            content = resp["choices"][0]["message"]["content"]
            return {"tokens": tokens, "content": content}
        except Exception as e:
            return {"error": str(e)}

    def do_HEAD(self):
        """Render 健康检查"""
        self.send_response(200); self.end_headers()

    def do_GET(self):
        if self.path == "/api/stats":
            with sqlite3.connect(DB) as c:
                c.row_factory = sqlite3.Row
                users = c.execute('''SELECT install_id, SUM(tokens) as t, SUM(cost_yuan) as c,
                    COUNT(*) as n, MAX(created_at) as last 
                    FROM usage_logs GROUP BY install_id ORDER BY t DESC''').fetchall()
                daily = c.execute('''SELECT date(created_at) as d, SUM(tokens) as t
                    FROM usage_logs GROUP BY d ORDER BY d DESC LIMIT 30''').fetchall()
                total_tokens = sum(r["t"] for r in users)
                total_cost = sum(r["c"] for r in users)
                total_users = len(users)
                today = c.execute("SELECT COALESCE(SUM(tokens),0) FROM usage_logs WHERE date(created_at)=date('now','localtime')").fetchone()[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"users":[dict(r) for r in users],
                "daily":[dict(r) for r in daily], "total_tokens":total_tokens, 
                "total_cost":round(total_cost,4), "total_users":total_users, "today":today}, ensure_ascii=False).encode())
        elif self.path == "/version":
            # 从 GitHub Release 获取最新版本信息，失败时使用硬编码版本
            version = "1.1.0"
            mac_url = "https://github.com/xianzhiming6-svg/sayai-dashboard/releases/latest/download/说AI懂的话-Mac-更新版.zip"
            win_url = "https://github.com/xianzhiming6-svg/sayai-dashboard/releases/latest/download/说AI懂的话-Windows.zip"
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/xianzhiming6-svg/sayai-dashboard/releases/latest",
                    headers={"User-Agent": "sayai-server/1.0"})
                r = json.loads(urllib.request.urlopen(req, timeout=8).read())
                latest = (r.get("tag_name") or "").lstrip("v")
                if latest:
                    version = latest
                    assets = r.get("assets", [])
                    for a in assets:
                        name = a.get("name", "")
                        if "Mac" in name: mac_url = a["browser_download_url"]
                        if "Windows" in name: win_url = a["browser_download_url"]
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "version": version, "mac_url": mac_url, "win_url": win_url
            }).encode())
        elif self.path == "/check_activation":
            iid = self.path.split("?id=")[-1] if "?id=" in self.path else ""
            active = False; expires = ""
            if iid:
                with sqlite3.connect(DB) as c:
                    r = c.execute("SELECT expires_at FROM activations WHERE install_id=? AND expires_at>=date('now')", (iid,)).fetchone()
                    if r: active = True; expires = r[0]
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
            self.wfile.write(json.dumps({"active":active,"expires":expires}).encode())
        elif self.path == "/" or self.path == "":
            html = DASHBOARD_HTML
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.send_response(404); self.end_headers()

DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🐣 说AI懂的话 · 监控仪表盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&display=swap');
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Noto Sans SC',sans-serif;background:linear-gradient(135deg,#fce4ec 0%,#e8f5e9 100%);min-height:100vh;padding:20px}
  .header{text-align:center;padding:30px 0 20px}
  .header h1{font-size:2em;color:#e91e63}.header p{color:#999;margin-top:8px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;max-width:900px;margin:0 auto 30px}
  .card{background:#fff;border-radius:20px;padding:20px;text-align:center;box-shadow:0 4px 15px rgba(0,0,0,0.06);transition:transform .2s}
  .card:hover{transform:translateY(-4px)}
  .card .icon{font-size:2.5em}.card .num{font-size:2em;font-weight:700;color:#333;margin:8px 0}
  .card .label{font-size:.9em;color:#999}
  .card.pink{border-bottom:4px solid #f48fb1}.card.green{border-bottom:4px solid #a5d6a7}
  .card.blue{border-bottom:4px solid #90caf9}.card.purple{border-bottom:4px solid #ce93d8}
  .charts{max-width:900px;margin:0 auto;display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .chart-box{background:#fff;border-radius:20px;padding:20px;box-shadow:0 4px 15px rgba(0,0,0,0.06)}
  .chart-box h3{text-align:center;color:#666;margin-bottom:15px;font-size:1.1em}
  .chart-box.full{grid-column:1/-1}
  table{width:100%;border-collapse:collapse;font-size:.9em}
  th,td{padding:10px 8px;text-align:center;border-bottom:1px solid #f0f0f0}
  th{background:#fafafa;color:#888;font-weight:400}
  tr:hover{background:#f9f9f9}
  .emoji-id{font-family:monospace;font-size:.75em;color:#aaa}
  @media(max-width:600px){.charts{grid-template-columns:1fr}}
  .refresh{text-align:center;margin-top:20px;color:#bbb;font-size:.8em}
</style>
</head>
<body>
<div class="header">
  <h1>🐣 说AI懂的话</h1>
  <p>监控仪表盘 · 实时数据</p>
</div>
<div class="cards">
  <div class="card pink">
    <div class="icon">👥</div><div class="num" id="users">-</div><div class="label">总用户</div>
  </div>
  <div class="card green">
    <div class="icon">✨</div><div class="num" id="today">-</div><div class="label">今日 Token</div>
  </div>
  <div class="card blue">
    <div class="icon">🔥</div><div class="num" id="total">-</div><div class="label">累计 Token</div>
  </div>
  <div class="card purple">
    <div class="icon">💰</div><div class="num" id="cost">-</div><div class="label">累计费用 (元)</div>
  </div>
</div>
<div class="charts">
  <div class="chart-box"><h3>📈 每日 Token 用量</h3><canvas id="dailyChart"></canvas></div>
  <div class="chart-box"><h3>👤 用户用量分布</h3><canvas id="userChart"></canvas></div>
  <div class="chart-box full"><h3>📋 用户明细</h3>
    <table><thead><tr><th>安装ID</th><th>翻译次数</th><th>Token 数</th><th>费用 (元)</th><th>最后活跃</th></tr></thead><tbody id="userTable"></tbody></table>
  </div>
</div>
<div class="refresh">每 30 秒自动刷新</div>
<script>
const fmt = n => {if(n>=1e6)return (n/1e6).toFixed(1)+'M';if(n>=1e3)return (n/1e3).toFixed(1)+'K';return n};
const colors = ['#f48fb1','#a5d6a7','#90caf9','#ce93d8','#ffcc80','#80cbc4','#ef9a9a'];
let dailyCtx, userCtx, dailyChart, userChart;
async function load(){
  try{
    const r = await fetch('/api/stats'); const d = await r.json();
    document.getElementById('users').textContent = d.total_users;
    document.getElementById('today').textContent = fmt(d.today);
    document.getElementById('total').textContent = fmt(d.total_tokens);
    document.getElementById('cost').textContent = '¥'+d.total_cost.toFixed(2);
    if(!dailyCtx){dailyCtx=document.getElementById('dailyChart').getContext('2d');userCtx=document.getElementById('userChart').getContext('2d');}
    const dl = d.daily.reverse();
    if(dailyChart) dailyChart.destroy();
    dailyChart = new Chart(dailyCtx,{type:'line',data:{labels:dl.map(r=>r.d),datasets:[{label:'Token',data:dl.map(r=>r.t),borderColor:'#f48fb1',backgroundColor:'rgba(244,143,177,0.1)',fill:true,tension:.4,pointRadius:4,pointBackgroundColor:'#f48fb1'}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{callback:v=>fmt(v)}}}}});
    if(userChart) userChart.destroy();
    userChart = new Chart(userCtx,{type:'bar',data:{labels:d.users.map(r=>r.install_id.slice(0,6)+'...'),datasets:[{label:'Token',data:d.users.map(r=>r.t),backgroundColor:d.users.map((_,i)=>colors[i%colors.length]),borderRadius:8}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{callback:v=>fmt(v)}}}}});
    let tb='';d.users.forEach(r=>{tb+=`<tr><td><span class="emoji-id">${r.install_id}</span></td><td>${r.n}</td><td>${fmt(r.t)}</td><td>¥${r.c.toFixed(4)}</td><td>${r.last||'-'}</td></tr>`});
    document.getElementById('userTable').innerHTML=tb||'<tr><td colspan="5">暂无数据 🐣</td></tr>';
  }catch(e){console.error(e)}
}
load();setInterval(load,30000);
</script>
</body>
</html>'''

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"🐣 监控仪表盘已启动 → http://0.0.0.0:{port}")
    server.serve_forever()
