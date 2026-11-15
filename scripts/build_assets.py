#!/usr/bin/env python3
"""Rebuild the README images (needs google-chrome). Run from the repo root.

Screenshots of the web panel are real: they come from the actual panel running on
demo data. Terminal screenshots are real command output rendered as HTML.
"""
import html
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from setu import cli, config, qr, system, web  # noqa: E402
from setu import state as S  # noqa: E402

OUT = os.path.join(ROOT, "assets")
CHROME = os.environ.get("CHROME", "google-chrome")


def shot(html_text, name, w, h, scale=2, budget=None):
    src = os.path.join(OUT, "src", name + ".html")
    with open(src, "w") as f:
        f.write(html_text)
    cmd = [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=%d" % scale, "--window-size=%d,%d" % (w, h),
           "--screenshot=" + os.path.join(OUT, name + ".png")]
    if budget:
        cmd.append("--virtual-time-budget=%d" % budget)
    subprocess.run(cmd + ["file://" + src], check=True, capture_output=True)


def demo_state():
    st = S.new_state("203.0.113.42")
    for n, days in (("alice-phone", None), ("alice-laptop", None), ("bob-iphone", None), ("guest-tv", 3)):
        S.add_device(st, n, expires_days=days)
    st["devices"]["bob-iphone"]["enabled"] = False
    return st


FONT = "ui-monospace,'DejaVu Sans Mono',Menlo,Consolas,monospace"
TERM = """<!doctype html><meta charset=utf-8><body style="margin:0;background:#0b1220;font-family:system-ui">
<div style="width:{w}px;padding:28px;box-sizing:border-box"><div style="background:#0f172a;border:1px solid #243049;border-radius:14px;overflow:hidden;box-shadow:0 20px 50px #0008">
<div style="background:#162033;padding:10px 14px;display:flex;gap:8px;align-items:center"><i style="width:12px;height:12px;border-radius:50%;background:#f87171"></i><i style="width:12px;height:12px;border-radius:50%;background:#fbbf24"></i><i style="width:12px;height:12px;border-radius:50%;background:#34d399"></i><span style="color:#8da0bf;font:13px {font};margin-left:10px">{title}</span></div>
<pre style="margin:0;padding:18px 20px;color:#e2e8f0;font:14px/1.5 {font};white-space:pre-wrap">{body}</pre></div></div></body>"""


def term(body_html, title, name, w=860, h=600):
    shot(TERM.format(w=w, font=FONT, title=title, body=body_html), name, w, h)


def prompt(cmd):
    return '<span style="color:#34d399">$</span> <span style="color:#fff">%s</span>\n' % html.escape(cmd)


def qr_html(text, px=5):
    svg = qr.to_svg(qr.make(text, "L"), 3, px)
    return '<div style="background:#fff;display:inline-block;padding:2px;border-radius:6px;line-height:0">%s</div>' % svg


def main():
    tmp = tempfile.mkdtemp()
    system.ETC = os.path.join(tmp, "etc")
    system.ROOT = os.path.join(tmp, "root")
    os.makedirs(system.ETC)
    with open(os.path.join(system.ETC, "blocklist.hosts"), "w") as f:
        f.write("".join("0.0.0.0 d%d.example\n" % i for i in range(87412)))
    st = demo_state()
    store = S.Store(os.path.join(tmp, "state.json"))
    token = S.set_web_token(st, "demo")
    store.save(st)
    now = time.time()
    stats = {
        st["devices"]["alice-phone"]["public_key"]: {"endpoint": "198.51.100.8:40122", "handshake": int(now - 14), "rx": 1_840_000_000, "tx": 96_000_000},
        st["devices"]["alice-laptop"]["public_key"]: {"endpoint": "198.51.100.8:51311", "handshake": int(now - 7200), "rx": 5_300_000_000, "tx": 410_000_000},
        st["devices"]["guest-tv"]["public_key"]: {"endpoint": None, "handshake": 0, "rx": 0, "tx": 0},
    }
    system.wg_dump = lambda *_a, **_k: stats
    # --- web panel screenshots (real panel, demo data) ---
    page = web.PAGE.replace("let tok=sessionStorage.tok||'';", "let tok='demo';")
    shot_page = page + "<script>setTimeout(()=>show('alice-phone'),500)</script>"
    web.PAGE = page
    srv = web.serve(store, system.Runner(True), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % srv.server_address[1]
    for name, extra, w, h in (("panel", "", 1100, 800), ("panel-qr", "<script>setTimeout(()=>show('alice-phone'),500)</script>", 1100, 760)):
        web.PAGE = page.replace("</body>", extra + "</body>")
        subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--window-size=%d,%d" % (w, h), "--virtual-time-budget=5000",
                        "--screenshot=" + os.path.join(OUT, name + ".png"), base], check=True, capture_output=True)
    srv.shutdown()
    # --- terminal screenshots ---
    d = st["devices"]["alice-phone"]
    conf = config.render_client_conf(st, d)
    deploy = (prompt("export HCLOUD_TOKEN=...   # from console.hetzner.cloud, 1 minute") +
              prompt("setu deploy hetzner --region hel1 --first-device alice-phone") +
              "Creating hetzner server 'setu-vpn' in hel1 ...\n\n"
              "Your server is at 203.0.113.42. Scan this with the WireGuard app:\n\n" + qr_html(conf) +
              "\n\nSaved in ./setu-output: alice-phone.conf, alice-phone.png, admin-token.txt\n"
              "The server needs about 2-3 minutes to finish installing; connect after that.\n"
              "Web panel (while connected): http://10.66.66.1:8080   (token in admin-token.txt)")
    term(deploy, "~ - zsh", "terminal-deploy", 860, 700)
    cli_out = (prompt("setu add bob-iphone --expires 7") +
               "Added bob-iphone (10.66.66.4)\n\nScan with the WireGuard app:\n\n" + qr_html(config.render_client_conf(st, st["devices"]["bob-iphone"]), 4) + "\n" +
               prompt("setu list") +
               "DEVICE               IP             STATE       LAST SEEN  EXPIRES\n"
               "alice-phone          10.66.66.2     <span style=\"color:#34d399\">online</span>      14s ago    -\n"
               "alice-laptop         10.66.66.3     idle        2h ago     -\n"
               "bob-iphone           10.66.66.4     idle        never      2026-11-22\n" +
               prompt("setu dns block tiktok.com") + "Done.\n" + prompt("setu doctor") +
               "  <span style=\"color:#34d399\">OK  </span> WireGuard tools installed\n"
               "  <span style=\"color:#34d399\">OK  </span> Interface wg0 is up\n"
               "  <span style=\"color:#34d399\">OK  </span> IPv4 forwarding enabled\n"
               "  <span style=\"color:#34d399\">OK  </span> Listening on UDP 51820\n"
               "  <span style=\"color:#34d399\">OK  </span> NAT (masquerade) rule present\n"
               "  <span style=\"color:#34d399\">OK  </span> DNS filter (setu-dns) running\n"
               "  <span style=\"color:#34d399\">OK  </span> Blocklist loaded (87412 domains)\n"
               "  <span style=\"color:#34d399\">OK  </span> Devices connected in the last 5 min: 1 of 3\n\nAll good.")
    term(cli_out, "root@setu-vpn: ~", "terminal-cli", 860, 920)
    print("assets built")


LOGO = open(os.path.join(OUT, "logo.svg")).read()

SOCIAL = """<!doctype html><meta charset=utf-8><style>
*{box-sizing:border-box}body{margin:0;width:1280px;height:640px;background:radial-gradient(1000px 600px at 85% 20%,#0f766e 0,#0b2a3a 55%,#08121f 100%);color:#fff;font-family:'Noto Sans','DejaVu Sans',system-ui,sans-serif;position:relative;overflow:hidden}
.logo svg,.l svg{width:100%;height:100%}.logo{position:absolute;left:96px;top:150px;width:300px;height:300px;filter:drop-shadow(0 20px 40px #0008)}
.t{position:absolute;left:470px;top:120px;right:80px}h1{font-size:128px;line-height:1;margin:0;letter-spacing:-3px}
p{font-size:38px;line-height:1.3;margin:22px 0 0;color:#c9e9e4}
.chips{position:absolute;left:470px;top:440px;display:flex;gap:14px;flex-wrap:wrap;width:760px}.chips span{background:#ffffff16;border:1px solid #ffffff30;border-radius:999px;padding:9px 20px;font-size:24px;color:#e6fffb}
.url{position:absolute;left:96px;bottom:40px;font-size:24px;color:#7dd3c8;letter-spacing:.5px}
.wave{position:absolute;right:-40px;bottom:-60px;width:700px;opacity:.12}
</style><body><div class=logo>__LOGO__</div>
<div class=t><h1>Setu</h1><p>Your own WireGuard VPN in one command.</p></div>
<div class=chips><span>One-command deploy</span><span>QR codes</span><span>Ad-blocking DNS</span><span>Web panel</span><span>Open source (MIT)</span></div>
<div class=url>github.com/AnuragRoy485/setu</div></body>"""

BANNER = """<!doctype html><meta charset=utf-8><style>
*{box-sizing:border-box}.l svg{width:100%;height:100%}body{margin:0;width:1280px;height:360px;background:linear-gradient(120deg,#08121f,#0b3b4a 60%,#0f766e);color:#fff;font-family:'Noto Sans','DejaVu Sans',system-ui,sans-serif;display:flex;align-items:center;gap:56px;padding:0 90px}
.l{width:210px;height:210px;flex:none;filter:drop-shadow(0 14px 30px #0007)}h1{font-size:104px;margin:0;line-height:1;letter-spacing:-2px}
p{font-size:32px;margin:12px 0 0;color:#c9e9e4}
</style><body><div class=l>__LOGO__</div><div><h1>Setu</h1><p>Your own WireGuard VPN in one command.</p></div></body>"""

ARCH = """<!doctype html><meta charset=utf-8><style>body{margin:0;background:#0b1220;font-family:'Noto Sans','DejaVu Sans',system-ui,sans-serif}</style>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 560" width="1200" height="560">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#5eead4"/></marker>
<marker id="g" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#94a3b8"/></marker></defs>
<style>.b{fill:#121b2e;stroke:#2a3a5c;stroke-width:2}.t{fill:#e6edf7;font-size:22px;font-weight:700}.s{fill:#8da0bf;font-size:17px}.k{fill:#5eead4;font-size:16px;font-weight:600}.h{fill:#5eead4;font-size:15px;letter-spacing:2px}</style>
<rect width="1200" height="560" fill="#0b1220"/>
<text x="40" y="44" class="h">HOW SETU WORKS</text>
<!-- you -->
<rect x="40" y="90" width="250" height="150" rx="16" class="b"/><text x="64" y="132" class="t">Your computer</text>
<text x="64" y="162" class="s">$ setu deploy hetzner</text><text x="64" y="190" class="s">Makes keys, builds the</text><text x="64" y="212" class="s">server, shows a QR code</text>
<rect x="40" y="330" width="250" height="150" rx="16" class="b"/><text x="64" y="372" class="t">Your devices</text>
<text x="64" y="402" class="s">Phone, laptop, tablet.</text><text x="64" y="430" class="s">Scan the QR in the</text><text x="64" y="452" class="s">WireGuard app</text>
<!-- cloud -->
<rect x="470" y="60" width="230" height="110" rx="16" class="b"/><text x="494" y="102" class="t">Cloud provider</text><text x="494" y="132" class="s">Hetzner, DigitalOcean,</text><text x="494" y="154" class="s">Vultr, or any SSH box</text>
<!-- server -->
<rect x="440" y="250" width="420" height="270" rx="18" class="b" stroke="#14b8a6"/>
<text x="468" y="292" class="t">Your Setu server</text>
<rect x="468" y="312" width="170" height="58" rx="10" fill="#0e1627" stroke="#2a3a5c"/><text x="484" y="347" class="s">WireGuard wg0</text>
<rect x="656" y="312" width="180" height="58" rx="10" fill="#0e1627" stroke="#2a3a5c"/><text x="672" y="347" class="s">NAT + firewall</text>
<rect x="468" y="384" width="170" height="58" rx="10" fill="#0e1627" stroke="#2a3a5c"/><text x="484" y="419" class="s">Ad-blocking DNS</text>
<rect x="656" y="384" width="180" height="58" rx="10" fill="#0e1627" stroke="#2a3a5c"/><text x="672" y="419" class="s">Web panel (VPN only)</text>
<text x="468" y="480" class="s">state.json = single source of truth</text><text x="468" y="504" class="s">daily timer: expire guests, refresh lists</text>
<!-- internet -->
<rect x="950" y="300" width="210" height="170" rx="16" class="b"/><text x="974" y="342" class="t">The internet</text><text x="974" y="372" class="s">Sites see your</text><text x="974" y="396" class="s">server's IP, not</text><text x="974" y="420" class="s">yours</text>
<!-- arrows -->
<path d="M290 150 H460" stroke="#94a3b8" stroke-width="3" stroke-dasharray="7 6" marker-end="url(#g)"/><text x="318" y="138" class="s">create via API</text>
<path d="M290 190 C380 190 400 260 440 290" stroke="#94a3b8" stroke-width="3" stroke-dasharray="7 6" marker-end="url(#g)" fill="none"/><text x="300" y="262" class="s">cloud-init installs</text>
<path d="M290 405 H440" stroke="#5eead4" stroke-width="5" marker-start="url(#a)" marker-end="url(#a)"/><text x="296" y="388" class="k">encrypted UDP 51820</text>
<path d="M860 385 H950" stroke="#5eead4" stroke-width="5" marker-end="url(#a)"/><text x="868" y="368" class="k">clear traffic</text>
<path d="M165 240 V330" stroke="#94a3b8" stroke-width="3" stroke-dasharray="7 6" marker-end="url(#g)"/><text x="178" y="292" class="s">QR / .conf</text>
</svg>"""


def more():
    logo = LOGO
    shot(SOCIAL.replace("__LOGO__", logo), "social-preview", 1280, 640, scale=1)
    shot(BANNER.replace("__LOGO__", logo), "banner", 1280, 360, scale=1)
    shot(ARCH, "architecture", 1200, 560, scale=1)
    shot("<body style='margin:0;background:transparent'><div style='width:512px;height:512px'>%s</div></body>" % logo, "logo", 512, 512, scale=1)


if __name__ == "__main__":
    main()
    more()
