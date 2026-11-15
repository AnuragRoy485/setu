"""Small web panel. Binds to the VPN address only, so you must be connected to use it."""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from . import config, qr, state as S, system
from .state import SetuError

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setu</title>
<style>
:root{--bg:#0b1220;--card:#121b2e;--line:#22304d;--fg:#e6edf7;--mut:#8da0bf;--acc:#2dd4bf;--bad:#f87171}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--line)}
header svg{width:34px;height:34px}h1{font-size:18px;margin:0}main{max-width:960px;margin:0 auto;padding:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
input,button{font:inherit;border-radius:8px;border:1px solid var(--line);background:#0e1627;color:var(--fg);padding:8px 12px}
button{cursor:pointer;background:var(--acc);color:#04201c;border:0;font-weight:600}button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
button.bad{background:transparent;color:var(--bad);border:1px solid var(--bad)}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 6px;white-space:nowrap;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:500}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#475569;margin-right:6px}.on{background:var(--acc)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.mut{color:var(--mut)}dialog{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:12px}
dialog img{width:260px;height:260px;background:#fff;border-radius:8px}
</style></head><body>
<header><svg viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#0f766e"/>
  <!-- suspension bridge: two towers, main cable, hangers, deck -->
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
<dialog id="dlg"><div id="dlgbody"></div><div class="row" style="margin-top:12px"><a id="dl"><button>Download .conf</button></a><button class="ghost" onclick="dlg.close()">Close</button></div></dialog>
<script>
const $=s=>document.querySelector(s),app=$('#app'),dlg=$('#dlg');let tok=sessionStorage.tok||'';
const api=async(p,o={})=>{const r=await fetch(p,{...o,headers:{...(o.headers||{}),Authorization:'Bearer '+tok,'Content-Type':'application/json'}});
 if(r.status==401){sessionStorage.removeItem('tok');tok='';login();throw 0}if(!r.ok)throw new Error((await r.json()).error||r.statusText);return r};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=b=>b>1e9?(b/1e9).toFixed(2)+' GB':b>1e6?(b/1e6).toFixed(1)+' MB':b>1e3?(b/1e3).toFixed(0)+' KB':b+' B';
const ago=t=>{if(!t)return 'never';const s=Math.floor(Date.now()/1000-t);return s<60?s+'s ago':s<3600?Math.floor(s/60)+'m ago':s<86400?Math.floor(s/3600)+'h ago':Math.floor(s/86400)+'d ago'};
function login(){$('#out').hidden=true;app.innerHTML='<div class="card"><h3>Sign in</h3><p class="mut">Paste the admin token printed when the server was set up.</p><form class="row" id="f"><input id="t" type="password" placeholder="admin token" size="40" autofocus><button>Sign in</button></form><p id="e" style="color:var(--bad)"></p></div>';
 $('#f').onsubmit=async e=>{e.preventDefault();tok=$('#t').value.trim();try{await api('/api/status');sessionStorage.tok=tok;load()}catch(x){if(x)$('#e').textContent=x.message}}}
async function load(){$('#out').hidden=false;const [s,d]=await Promise.all([api('/api/status').then(r=>r.json()),api('/api/devices').then(r=>r.json())]);$('#ver').textContent='v'+s.version;
 app.innerHTML=`<div class="card row"><div><b>${esc(s.endpoint)}:${s.port}</b><div class="mut">${s.dns} DNS · ${s.blocked} blocked domains · ${d.devices.length} devices</div></div></div>
 <div class="card"><h3 style="margin-top:0">Add a device</h3><form class="row" id="add"><input id="n" placeholder="alice-phone" pattern="[a-z0-9][a-z0-9_-]{0,31}" required>
 <input id="x" type="number" min="1" placeholder="expires in days (optional)" style="width:210px"><button>Add</button></form><p id="ae" style="color:var(--bad)"></p></div>
 <div class="card"><table><tr><th>Device</th><th>IP</th><th>Last seen</th><th>Traffic</th><th></th></tr>${d.devices.map(v=>`<tr><td><span class="dot ${v.online?'on':''}"></span><b>${esc(v.name)}</b>${v.enabled?'':' <span class="mut">(paused)</span>'}${v.expires?'<div class="mut">expires '+esc(v.expires.slice(0,10))+'</div>':''}</td><td>${esc(v.ipv4)}</td><td>${ago(v.handshake)}</td><td>${fmt(v.rx)} ↓ ${fmt(v.tx)} ↑</td>
 <td><div class="row" style="flex-wrap:nowrap;justify-content:flex-end"><button class="ghost" onclick="show('${esc(v.name)}')">QR</button><button class="ghost" onclick="tog('${esc(v.name)}')">${v.enabled?'Pause':'Resume'}</button><button class="bad" onclick="del('${esc(v.name)}')">Remove</button></div></td></tr>`).join('')||'<tr><td colspan=5 class="mut">No devices yet.</td></tr>'}</table></div>`;
 $('#add').onsubmit=async e=>{e.preventDefault();try{const x=$('#x').value;await api('/api/devices',{method:'POST',body:JSON.stringify({name:$('#n').value,expires_days:x?+x:null})});await load();show($('#n')?.value||'')}catch(x){$('#ae').textContent=x.message}}}
async function show(n){if(!n)return;const r=await api('/api/devices/'+n+'/qr.svg');const svg=await r.text();$('#dlgbody').innerHTML='<h3>'+esc(n)+'</h3><p class="mut">Open the WireGuard app, tap + and scan this code.</p><img src="data:image/svg+xml;base64,'+btoa(svg)+'">';
 const c=await (await api('/api/devices/'+n+'/config')).text();$('#dl').href='data:text/plain;charset=utf-8,'+encodeURIComponent(c);$('#dl').download=n+'.conf';dlg.showModal()}
async function tog(n){await api('/api/devices/'+n+'/toggle',{method:'POST'});load()}
async function del(n){if(confirm('Remove '+n+'? Its config stops working immediately.')){await api('/api/devices/'+n,{method:'DELETE'});load()}}
$('#out').onclick=()=>{sessionStorage.removeItem('tok');tok='';login()};
tok?load().catch(()=>{}):login();
</script></body></html>"""


def device_view(dev: Dict[str, Any], peers: Dict[str, Any]) -> Dict[str, Any]:
    peer = peers.get(dev["public_key"], {})
    hs = peer.get("handshake", 0)
    return {"name": dev["name"], "user": dev["user"], "ipv4": dev["ipv4"], "enabled": dev.get("enabled", True),
            "expires": dev.get("expires"), "created": dev["created"], "handshake": hs,
            "online": hs > 0 and time.time() - hs < 180, "rx": peer.get("rx", 0), "tx": peer.get("tx", 0),
            "endpoint": peer.get("endpoint")}


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
