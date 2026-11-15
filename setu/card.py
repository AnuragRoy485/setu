"""A self-contained 'setup card': one HTML page with the QR code and plain steps for a new user.

The card holds the device's private key, so treat it like a password: send it over a
private chat, never post it. English, Hindi and Bengali are included.
"""
from __future__ import annotations

import html
import urllib.parse
from typing import Any, Dict

from . import config, qr

STRINGS = {
    "en": {
        "title": "Your private VPN",
        "hello": "Hi %s, this card sets up your VPN in about a minute.",
        "s1": "Install the free <b>WireGuard</b> app (App Store or Google Play).",
        "s2": "Open it, tap <b>+</b>, then <b>Scan from QR code</b>, and scan the code below.",
        "s2b": "On a computer: use <b>Import tunnel(s) from file</b> and choose the downloaded file.",
        "s3": "Turn the tunnel on. Visit ifconfig.me to check: it should show %s.",
        "warn": "Keep this private. Anyone with this code can use your VPN. Do not post it.",
        "dl": "Download config file",
    },
    "hi": {
        "title": "आपका निजी VPN",
        "hello": "नमस्ते %s, यह कार्ड एक मिनट में आपका VPN चालू कर देगा।",
        "s1": "मुफ़्त <b>WireGuard</b> ऐप इंस्टॉल करें (App Store या Google Play)।",
        "s2": "ऐप खोलें, <b>+</b> दबाएँ, फिर <b>Scan from QR code</b> चुनें और नीचे का कोड स्कैन करें।",
        "s2b": "कंप्यूटर पर: <b>Import tunnel(s) from file</b> चुनें और डाउनलोड की गई फ़ाइल दें।",
        "s3": "टनल चालू करें। जाँच के लिए ifconfig.me खोलें: उसमें %s दिखना चाहिए।",
        "warn": "इसे गोपनीय रखें। इस कोड वाला कोई भी आपका VPN इस्तेमाल कर सकता है। इसे कहीं पोस्ट न करें।",
        "dl": "कॉन्फ़िग फ़ाइल डाउनलोड करें",
    },
    "bn": {
        "title": "আপনার ব্যক্তিগত VPN",
        "hello": "নমস্কার %s, এই কার্ড এক মিনিটে আপনার VPN চালু করে দেবে।",
        "s1": "বিনামূল্যের <b>WireGuard</b> অ্যাপ ইনস্টল করুন (App Store বা Google Play)।",
        "s2": "অ্যাপ খুলে <b>+</b> চাপুন, তারপর <b>Scan from QR code</b> বেছে নিয়ে নিচের কোডটি স্ক্যান করুন।",
        "s2b": "কম্পিউটারে: <b>Import tunnel(s) from file</b> বেছে ডাউনলোড করা ফাইলটি দিন।",
        "s3": "টানেল চালু করুন। যাচাই করতে ifconfig.me খুলুন: সেখানে %s দেখা উচিত।",
        "warn": "এটি গোপন রাখুন। এই কোড যার কাছে থাকবে সে আপনার VPN ব্যবহার করতে পারবে। কোথাও পোস্ট করবেন না।",
        "dl": "কনফিগ ফাইল ডাউনলোড করুন",
    },
}

LANGS = sorted(STRINGS)


def render(st: Dict[str, Any], dev: Dict[str, Any], lang: str = "en") -> str:
    if lang not in STRINGS:
        raise ValueError("language must be one of: %s" % ", ".join(LANGS))
    t = STRINGS[lang]
    text = config.render_client_conf(st, dev)
    svg = qr.to_svg(qr.make(text, "L"), 4, 8)
    name = html.escape(dev["name"])
    endpoint = html.escape(st["server"]["endpoint"])
    href = "data:text/plain;charset=utf-8," + urllib.parse.quote(text)
    return """<!doctype html><html lang="%(lang)s"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setu - %(name)s</title>
<style>body{font:17px/1.6 system-ui,sans-serif;max-width:520px;margin:0 auto;padding:20px;color:#0f172a;background:#f8fafc}
h1{color:#0f766e;margin-bottom:4px}.qr{background:#fff;border:1px solid #cbd5e1;border-radius:12px;padding:12px;text-align:center}
.qr svg{width:100%%;max-width:320px;height:auto}ol{padding-left:22px}li{margin:10px 0}
.warn{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 14px;margin-top:18px}
a.btn{display:inline-block;margin-top:14px;padding:10px 16px;border-radius:8px;background:#0f766e;color:#fff;text-decoration:none}
@media print{a.btn{display:none}}</style></head><body>
<h1>%(title)s</h1><p>%(hello)s</p>
<ol><li>%(s1)s</li><li>%(s2)s<br><small>%(s2b)s</small></li><li>%(s3)s</li></ol>
<div class="qr">%(svg)s</div>
<p><a class="btn" download="%(name)s.conf" href="%(href)s">%(dl)s</a></p>
<div class="warn">%(warn)s</div></body></html>
""" % {"lang": lang, "name": name, "title": t["title"], "hello": t["hello"] % name, "s1": t["s1"],
       "s2": t["s2"], "s2b": t["s2b"], "s3": t["s3"] % endpoint, "svg": svg, "href": href, "dl": t["dl"],
       "warn": t["warn"]}
