"""Small web panel. Binds to the VPN address only, so you must be connected to use it."""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from . import config, doctor, qr, state as S, system, usage
from .state import SetuError

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setu</title>
<style>
:root{--bg:#0b1220;--card:#121b2e;--line:#22304d;--fg:#e6edf7;--mut:#8da0bf;--acc:#2dd4bf;--bad:#f87171;--blue:#60a5fa;--ok:#34d399;--warn:#fbbf24;--inp:#0e1627}
@media(prefers-color-scheme:light){:root{--bg:#f1f5f9;--card:#fff;--line:#d5deea;--fg:#0f172a;--mut:#5b6b85;--acc:#0f766e;--bad:#dc2626;--blue:#2563eb;--ok:#059669;--warn:#b45309;--inp:#f8fafc}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line)}
header svg{width:34px;height:34px}h1{font-size:18px;margin:0}main{max-width:1000px;margin:0 auto;padding:20px}h3{margin:0 0 10px;font-size:15px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
input,button,select{font:inherit;border-radius:8px;border:1px solid var(--line);background:var(--inp);color:var(--fg);padding:7px 11px}
button{cursor:pointer;background:var(--acc);color:#fff;border:0;font-weight:600}button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
button.bad{background:transparent;color:var(--bad);border:1px solid var(--bad)}button.sm{padding:4px 9px;font-size:13px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:middle}th{color:var(--mut);font-weight:500;font-size:13px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#64748b;margin-right:6px}.on{background:var(--ok)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.mut{color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat{background:var(--inp);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.stat b{display:block;font-size:20px}.stat span{color:var(--mut);font-size:12px}
dialog{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:12px;max-width:560px;width:calc(100% - 24px)}dialog::backdrop{background:#0008}
dialog img{width:260px;height:260px;background:#fff;border-radius:8px;display:block;margin:8px auto}
.pill{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mut)}.pill.ok{color:var(--ok);border-color:var(--ok)}.pill.fail{color:var(--bad);border-color:var(--bad)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px}svg.chart{width:100%;height:auto;display:block}
.tbl{overflow-x:auto}.tag{color:var(--warn);font-size:12px}
</style></head><body>
<header><svg viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#0f766e"/>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M150 140 V344 M362 140 V344" stroke="#ffffff" stroke-width="34"/>
    <path d="M150 150 Q256 330 362 150" stroke="#ffffff" stroke-width="16"/>
    <path d="M150 150 Q96 220 60 322 M362 150 Q416 220 452 322" stroke="#ffffff" stroke-width="16"/>
    <path d="M203 218 V344 M256 240 V344 M309 218 V344" stroke="#5eead4" stroke-width="12"/>
    <path d="M48 350 H464" stroke="#ffffff" stroke-width="30"/>
    <path d="M104 410 q38 -22 76 0 t76 0 t76 0 t76 0" stroke="#5eead4" stroke-opacity=".7" stroke-width="14"/>
  </g>
  <circle cx="150" cy="118" r="17" fill="#5eead4"/><circle cx="362" cy="118" r="17" fill="#5eead4"/>
</svg>
<h1>Setu <span class="mut" id="ver"></span></h1><span style="flex:1"></span><button class="ghost" id="out" hidden>Sign out</button></header>
<main id="app"></main>
<dialog id="dlg"><div id="dlgbody"></div><div class="row" style="margin-top:12px" id="dlgbtns"></div></dialog>
<script>
const $=s=>document.querySelector(s),app=$('#app'),dlg=$('#dlg');let tok=sessionStorage.tok||'',timer=null,filter='';
const api=async(p,o={})=>{const r=await fetch(p,{...o,headers:{...(o.headers||{}),Authorization:'Bearer '+tok,'Content-Type':'application/json'}});
 if(r.status==401){sessionStorage.removeItem('tok');tok='';login();throw 0}if(!r.ok)throw new Error((await r.json()).error||r.statusText);return r};
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=b=>b>=1e9?(b/1e9).toFixed(2)+' GB':b>=1e6?(b/1e6).toFixed(1)+' MB':b>=1e3?(b/1e3).toFixed(0)+' KB':b+' B';
const ago=t=>{if(!t)return 'never';const s=Math.floor(Date.now()/1000-t);return s<60?s+'s ago':s<3600?Math.floor(s/60)+'m ago':s<86400?Math.floor(s/3600)+'h ago':Math.floor(s/86400)+'d ago'};
const dur=s=>s==null?'-':s>=86400?Math.floor(s/86400)+'d '+Math.floor(s%86400/3600)+'h':s>=3600?Math.floor(s/3600)+'h '+Math.floor(s%3600/60)+'m':Math.floor(s/60)+'m';
const lab=t=>t.length>10?t.slice(11)+':00':t.slice(5);
function chart(pts,h,label){const w=600,n=pts.length,max=Math.max(1,...pts.map(p=>p.rx+p.tx)),bw=w/n;
 return '<svg class="chart" viewBox="0 0 '+w+' '+(h+18)+'" role="img" aria-label="'+esc(label)+'">'+pts.map((p,i)=>{const hr=p.rx/max*h,ht=p.tx/max*h,x=i*bw+1;
 return '<g><title>'+esc(p.t)+': '+fmt(p.rx)+' down, '+fmt(p.tx)+' up</title><rect x="'+x+'" y="'+(h-hr)+'" width="'+(bw-2)+'" height="'+hr+'" fill="var(--acc)"/><rect x="'+x+'" y="'+(h-hr-ht)+'" width="'+(bw-2)+'" height="'+ht+'" fill="var(--blue)"/></g>'}).join('')+
 '<line x1="0" x2="'+w+'" y1="'+h+'" y2="'+h+'" stroke="var(--line)"/><text x="0" y="'+(h+14)+'" font-size="11" fill="var(--mut)">'+esc(lab(pts[0].t))+'</text><text x="'+w+'" y="'+(h+14)+'" text-anchor="end" font-size="11" fill="var(--mut)">'+esc(lab(pts[n-1].t))+'</text></svg>'}
const spark=pts=>{const m=Math.max(1,...pts.map(p=>p.rx+p.tx)),w=84,h=22,b=w/pts.length;return '<svg width="'+w+'" height="'+h+'" aria-hidden="true">'+pts.map((p,i)=>{const v=(p.rx+p.tx)/m*h;return '<rect x="'+(i*b)+'" y="'+(h-v)+'" width="'+(b-1)+'" height="'+v+'" fill="var(--acc)" opacity=".8"/>'}).join('')+'</svg>'};
function login(){clearInterval(timer);$('#out').hidden=true;app.innerHTML='<div class="card"><h3>Sign in</h3><p class="mut">Paste the admin token printed when the server was set up.</p><form class="row" id="f"><input id="t" type="password" placeholder="admin token" size="40" autofocus><button>Sign in</button></form><p id="e" style="color:var(--bad)"></p></div>';
 $('#f').onsubmit=async e=>{e.preventDefault();tok=$('#t').value.trim();try{await api('/api/status');sessionStorage.tok=tok;load(true)}catch(x){if(x)$('#e').textContent=x.message}}}
let data=null;
async function load(first){$('#out').hidden=false;const [s,d,u,h]=await Promise.all([api('/api/status').then(r=>r.json()),api('/api/devices').then(r=>r.json()),api('/api/usage').then(r=>r.json()),api('/api/health').then(r=>r.json())]);data={s,d,u,h};$('#ver').textContent='v'+s.version;if(first||!$('#list'))skeleton();paint();
 if(first){clearInterval(timer);timer=setInterval(()=>{if(!dlg.open&&!document.hidden&&!document.activeElement.matches('input'))load().catch(()=>{})},20000)}}
function skeleton(){app.innerHTML='<div class="card" id="health"></div><div class="card" id="totals"></div>'+
 '<div class="card"><h3>Add a device</h3><form class="row" id="add"><input id="n" placeholder="alice-phone" pattern="[a-z0-9][a-z0-9_-]{0,31}" required>'+
 '<input id="x" type="number" min="1" placeholder="expires in days (optional)" style="width:240px"><button>Add</button></form><p id="ae" style="color:var(--bad)"></p></div>'+
 '<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h3 style="margin:0">Devices</h3><input id="q" placeholder="Search devices" type="search"></div><div class="tbl" id="list"></div></div>';
 $('#add').onsubmit=async e=>{e.preventDefault();const n=$('#n').value;try{const x=$('#x').value;await api('/api/devices',{method:'POST',body:JSON.stringify({name:n,expires_days:x?+x:null})});$('#n').value='';$('#x').value='';await load();show(n)}catch(x){$('#ae').textContent=x.message}};
 $('#q').oninput=e=>{filter=e.target.value.toLowerCase();paint()};
 $('#list').onclick=async e=>{const b=e.target.closest('button[data-a]');if(!b)return;const n=b.dataset.n,a=b.dataset.a;
  if(a=='qr')show(n);else if(a=='use')usage(n);else if(a=='tog'){await api('/api/devices/'+n+'/toggle',{method:'POST'});load()}
  else if(a=='exp')expiry(n);else if(a=='del'&&confirm('Remove '+n+'? Its config stops working immediately.')){await api('/api/devices/'+n,{method:'DELETE'});load()}}}
function paint(){const {s,d,u,h}=data,sy=h.system||{};
 $('#health').innerHTML='<div class="row" style="justify-content:space-between"><h3 style="margin:0">Server <span class="pill '+(h.ok?'ok':'fail')+'">'+(h.ok?'healthy':'needs attention')+'</span></h3><span class="mut">'+esc(s.endpoint)+':'+s.port+' &middot; '+esc(s.dns)+' DNS &middot; '+s.blocked+' blocked domains</span></div>'+
 '<div class="grid" style="margin-top:10px"><div class="stat"><b>'+dur(sy.uptime_s)+'</b><span>uptime</span></div><div class="stat"><b>'+(sy.load?sy.load[0].toFixed(2):'-')+'</b><span>load (1 min)</span></div><div class="stat"><b>'+(sy.mem_used_pct==null?'-':sy.mem_used_pct+'%')+'</b><span>memory used</span></div><div class="stat"><b>'+(sy.disk_free_pct==null?'-':sy.disk_free_pct+'%')+'</b><span>disk free</span></div></div>'+
 h.checks.filter(c=>!c.ok).map(c=>'<p class="tag">&#9888; '+esc(c.name)+(c.hint?' &mdash; '+esc(c.hint):'')+'</p>').join('');
 const tot=u.total_days,t30=tot.reduce((a,p)=>a+p.rx+p.tx,0),on=d.devices.filter(v=>v.online).length;
 $('#totals').innerHTML='<div class="row" style="justify-content:space-between"><h3 style="margin:0">Traffic, last 30 days</h3><span class="legend mut"><i style="background:var(--acc)"></i>download<i style="background:var(--blue)"></i>upload</span></div><p class="mut" style="margin:4px 0 8px"><b style="color:var(--fg)">'+fmt(t30)+'</b> total &middot; '+on+' of '+d.devices.length+' devices online now</p>'+chart(tot,90,'Total traffic per day');
 const rows=d.devices.filter(v=>!filter||v.name.includes(filter)||(v.note||'').toLowerCase().includes(filter));
 $('#list').innerHTML='<table><tr><th>Device</th><th>IP</th><th>Last seen</th><th>Today / 7 days</th><th></th></tr>'+rows.map(v=>{const us=(u.devices[v.name]||{days:[]}).days,today=us.length?us[us.length-1]:{rx:0,tx:0};
  return '<tr><td><span class="dot '+(v.online?'on':'')+'"></span><b>'+esc(v.name)+'</b>'+(v.enabled?'':' <span class="mut">(paused)</span>')+(v.expires?'<div class="mut">expires '+esc(v.expires.slice(0,10))+'</div>':'')+(v.note?'<div class="mut">'+esc(v.note)+'</div>':'')+'</td><td>'+esc(v.ipv4)+'</td><td>'+ago(v.handshake)+'</td><td>'+fmt(today.rx+today.tx)+' '+spark(us.slice(-7))+'</td>'+
  '<td><div class="row" style="flex-wrap:nowrap;justify-content:flex-end"><button class="ghost sm" data-a="qr" data-n="'+esc(v.name)+'">QR</button><button class="ghost sm" data-a="use" data-n="'+esc(v.name)+'">Usage</button><button class="ghost sm" data-a="tog" data-n="'+esc(v.name)+'">'+(v.enabled?'Pause':'Resume')+'</button><button class="ghost sm" data-a="exp" data-n="'+esc(v.name)+'">Expiry</button><button class="bad sm" data-a="del" data-n="'+esc(v.name)+'">Remove</button></div></td></tr>'}).join('')+(rows.length?'':'<tr><td colspan=5 class="mut">'+(filter?'No match.':'No devices yet.')+'</td></tr>')+'</table>'}
function dialog(html,btns){$('#dlgbody').innerHTML=html;$('#dlgbtns').innerHTML=btns+'<button class="ghost" id="cl">Close</button>';$('#cl').onclick=()=>dlg.close();dlg.showModal()}
async function show(n){if(!n)return;const svg=await (await api('/api/devices/'+n+'/qr.svg')).text(),c=await (await api('/api/devices/'+n+'/config')).text();
 dialog('<h3>'+esc(n)+'</h3><ol class="mut"><li>Install the free <b>WireGuard</b> app.</li><li>Tap <b>+</b>, then <b>Scan from QR code</b>.</li><li>Scan this code and switch the tunnel on.</li></ol><img alt="QR code for '+esc(n)+'" src="data:image/svg+xml;base64,'+btoa(svg)+'"><p class="mut" style="font-size:13px">This code holds the device key. Show it only to the person who owns the device.</p>',
 '<a id="dl" download="'+esc(n)+'.conf" href="data:text/plain;charset=utf-8,'+encodeURIComponent(c)+'"><button>Download .conf</button></a><button class="ghost" id="cp">Copy config</button>');
 $('#cp').onclick=async e=>{try{await navigator.clipboard.writeText(c);e.target.textContent='Copied'}catch(x){e.target.textContent='Copy failed'}}}
async function usage(n){const u=await (await api('/api/devices/'+n+'/usage')).json();
 dialog('<h3>'+esc(n)+' usage</h3><div class="grid"><div class="stat"><b>'+fmt(u.total_rx)+'</b><span>downloaded, 30 days</span></div><div class="stat"><b>'+fmt(u.total_tx)+'</b><span>uploaded, 30 days</span></div></div><p class="mut" style="margin:12px 0 4px">Last 24 hours</p>'+chart(u.hours,60,'Last 24 hours')+'<p class="mut" style="margin:12px 0 4px">Last 30 days</p>'+chart(u.days,60,'Last 30 days')+'<p class="mut" style="font-size:12px">Only byte counts are stored. No sites or IP addresses.</p>','')}
async function expiry(n){const v=prompt('Expire '+n+' in how many days from now? Leave empty for never.','');if(v===null)return;
 try{await api('/api/devices/'+n+'/expiry',{method:'POST',body:JSON.stringify({days:v.trim()?+v:null})});load()}catch(x){alert(x.message)}}
$('#out').onclick=()=>{sessionStorage.removeItem('tok');tok='';login()};
tok?load(true).catch(()=>{}):login();
</script></body></html>"""


def device_view(dev: Dict[str, Any], peers: Dict[str, Any]) -> Dict[str, Any]:
    peer = peers.get(dev["public_key"], {})
    hs = peer.get("handshake", 0)
    return {"name": dev["name"], "user": dev["user"], "ipv4": dev["ipv4"], "enabled": dev.get("enabled", True),
            "expires": dev.get("expires"), "created": dev["created"], "handshake": hs,
            "online": hs > 0 and time.time() - hs < 180, "rx": peer.get("rx", 0), "tx": peer.get("tx", 0),
            "endpoint": peer.get("endpoint"), "note": dev.get("note", "")}


class App:
    """The panel's logic, separate from HTTP so it can be tested directly."""

    def __init__(self, store: S.Store, runner: system.Runner):
        self.store, self.runner = store, runner

    def status(self) -> Dict[str, Any]:
        from . import __version__
        st = self.store.load()
        n = 0
        try:
            with open(system.ETC + "/blocklist.hosts") as f:
                n = sum(1 for _ in f)
        except OSError:
            pass
        return {"version": __version__, "endpoint": st["server"]["endpoint"], "port": st["server"]["port"],
                "dns": st["dns"]["mode"], "blocked": n, "devices": len(st["devices"])}

    def devices(self) -> Dict[str, Any]:
        st = self.store.load()
        peers = system.wg_dump(st, self.runner)
        return {"devices": [device_view(d, peers) for d in st["devices"].values()]}

    def usage_all(self, days: int = 30) -> Dict[str, Any]:
        st = self.store.load()
        return usage.overview(usage.load(), list(st["devices"]), days)

    def usage_one(self, name: str, days: int = 30) -> Dict[str, Any]:
        st = self.store.load()
        if name not in st["devices"]:
            raise SetuError("no device called %r" % name)
        return usage.series(usage.load(), name, days)

    def health(self) -> Dict[str, Any]:
        return doctor.summary(self.store.load(), self.runner)

    def set_expiry(self, name: str, days) -> Dict[str, Any]:
        with self.store.locked():
            st = self.store.load()
            exp = S.set_expiry(st, name, days)
            self.store.save(st)
        return {"name": name, "expires": exp}

    def add(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self.store.locked():
            st = self.store.load()
            dev = S.add_device(st, str(body.get("name", "")), body.get("public_key") or None,
                               body.get("expires_days"), body.get("allowed_ips") or None)
            self.store.save(st)
            system.apply(st, self.runner)
        return {"name": dev["name"]}

    def remove(self, name: str) -> None:
        with self.store.locked():
            st = self.store.load()
            S.remove_device(st, name)
            self.store.save(st)
            system.apply(st, self.runner)

    def toggle(self, name: str) -> bool:
        with self.store.locked():
            st = self.store.load()
            if name not in st["devices"]:
                raise SetuError("no device called %r" % name)
            d = st["devices"][name]
            d["enabled"] = not d.get("enabled", True)
            self.store.save(st)
            system.apply(st, self.runner)
        return d["enabled"]

    def config_text(self, name: str) -> str:
        st = self.store.load()
        if name not in st["devices"]:
            raise SetuError("no device called %r" % name)
        return config.render_client_conf(st, st["devices"][name])


ROUTES = [
    ("GET", re.compile(r"^/api/status$")), ("GET", re.compile(r"^/api/devices$")),
    ("GET", re.compile(r"^/api/usage$")), ("GET", re.compile(r"^/api/health$")),
    ("GET", re.compile(r"^/api/devices/([a-z0-9_-]+)/usage$")),
    ("POST", re.compile(r"^/api/devices/([a-z0-9_-]+)/expiry$")),
    ("POST", re.compile(r"^/api/devices$")), ("DELETE", re.compile(r"^/api/devices/([a-z0-9_-]+)$")),
    ("POST", re.compile(r"^/api/devices/([a-z0-9_-]+)/toggle$")),
    ("GET", re.compile(r"^/api/devices/([a-z0-9_-]+)/config$")),
    ("GET", re.compile(r"^/api/devices/([a-z0-9_-]+)/qr\.svg$")),
]


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "setu"

        def log_message(self, *a):  # keep the journal quiet; no client IPs or paths
            pass

        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:")
            self.end_headers()
            self.wfile.write(data)

        def _auth(self) -> bool:
            hdr = self.headers.get("Authorization", "")
            tok = hdr[7:] if hdr.startswith("Bearer ") else ""
            if S.check_web_token(app.store.load(), tok):
                return True
            time.sleep(0.4)  # slow down guessing
            return False

        def _handle(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            if method == "GET" and path in ("/", "/index.html"):
                return self._send(200, PAGE, "text/html")
            for m, rx in ROUTES:
                match = rx.match(path)
                if m == method and match:
                    break
            else:
                return self._send(404, {"error": "not found"})
            if not self._auth():
                return self._send(401, {"error": "unauthorized"})
            try:
                name = match.group(1) if match.groups() else None
                if path == "/api/status":
                    return self._send(200, app.status())
                if path == "/api/usage":
                    return self._send(200, app.usage_all())
                if path == "/api/health":
                    return self._send(200, app.health())
                if path.endswith("/usage"):
                    return self._send(200, app.usage_one(name))
                if path.endswith("/expiry"):
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 1000:
                        return self._send(413, {"error": "too large"})
                    body = json.loads(self.rfile.read(n) or b"{}")
                    return self._send(200, app.set_expiry(name, body.get("days")))
                if path == "/api/devices" and method == "GET":
                    return self._send(200, app.devices())
                if path == "/api/devices" and method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 10000:
                        return self._send(413, {"error": "too large"})
                    return self._send(201, app.add(json.loads(self.rfile.read(n) or b"{}")))
                if method == "DELETE":
                    app.remove(name)
                    return self._send(200, {"ok": True})
                if path.endswith("/toggle"):
                    return self._send(200, {"enabled": app.toggle(name)})
                if path.endswith("/config"):
                    return self._send(200, app.config_text(name), "text/plain")
                if path.endswith("/qr.svg"):
                    return self._send(200, qr.to_svg(qr.make(app.config_text(name), "L"), 4, 8), "image/svg+xml")
            except SetuError as e:
                return self._send(400, {"error": str(e)})
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": "bad request: %s" % e})
            return self._send(404, {"error": "not found"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_DELETE(self):
            self._handle("DELETE")

    return H


def serve(store: S.Store, runner: system.Runner, bind: str, port: int):
    srv = ThreadingHTTPServer((bind, port), make_handler(App(store, runner)))
    return srv
