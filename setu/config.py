"""Render WireGuard, firewall and DNS configuration from state."""
from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from .state import server_ips

DNS_PRESETS = {
    "cloudflare": ["1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"],
    "quad9": ["9.9.9.9", "149.112.112.112", "2620:fe::fe", "2620:fe::9"],
    "google": ["8.8.8.8", "8.8.4.4", "2001:4860:4860::8888", "2001:4860:4860::8844"],
    "adguard": ["94.140.14.14", "94.140.15.15", "2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"],
    "mullvad": ["194.242.2.2", "2a07:e340::2"],
}

BLOCKLISTS = {
    "ads": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "family": "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/"
              "fakenews-gambling-porn/hosts",
    "off": None,
}


def fmt_endpoint(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "%s:%d" % (host, port)


def uses_local_dns(st: Dict[str, Any]) -> bool:
    return st["dns"]["mode"] == "adblock"


def upstream_servers(st: Dict[str, Any]) -> List[str]:
    d = st["dns"]
    if d.get("custom"):
        return list(d["custom"])
    return DNS_PRESETS.get(d.get("upstream", "cloudflare"), DNS_PRESETS["cloudflare"])


def client_dns(st: Dict[str, Any]) -> List[str]:
    if uses_local_dns(st):
        v4, v6 = server_ips(st)
        return [str(v4), str(v6)]
    d = st["dns"]
    if d.get("custom"):
        return list(d["custom"])
    return DNS_PRESETS.get(d["mode"], DNS_PRESETS["cloudflare"])


def render_server_conf(st: Dict[str, Any]) -> str:
    s = st["server"]
    v4, v6 = server_ips(st)
    n4 = ipaddress.ip_network(s["ipv4_net"])
    n6 = ipaddress.ip_network(s["ipv6_net"])
    lines = [
        "# Managed by Setu - edits are overwritten. Use `setu add|remove` instead.",
        "[Interface]",
        "Address = %s/%d, %s/%d" % (v4, n4.prefixlen, v6, n6.prefixlen),
        "ListenPort = %d" % s["port"],
        "PrivateKey = %s" % s["private_key"],
        "PostUp = /etc/setu/postup.sh",
        "PostDown = /etc/setu/postdown.sh",
    ]
    if s.get("mtu"):
        lines.append("MTU = %d" % s["mtu"])
    for d in st["devices"].values():
        if not d.get("enabled", True):
            continue
        lines += ["", "# %s" % d["name"], "[Peer]", "PublicKey = %s" % d["public_key"],
                  "PresharedKey = %s" % d["psk"],
                  "AllowedIPs = %s/32, %s/128" % (d["ipv4"], d["ipv6"])]
    return "\n".join(lines) + "\n"


def render_client_conf(st: Dict[str, Any], dev: Dict[str, Any], endpoint: str = "") -> str:
    s = st["server"]
    ep = endpoint or s["endpoint"]
    n4 = ipaddress.ip_network(s["ipv4_net"])
    priv = dev.get("private_key") or "<PASTE YOUR PRIVATE KEY HERE>"
    lines = ["[Interface]", "# %s" % dev["name"], "PrivateKey = %s" % priv,
             "Address = %s/32, %s/128" % (dev["ipv4"], dev["ipv6"]),
             "DNS = %s" % ", ".join(client_dns(st))]
    if s.get("mtu"):
        lines.append("MTU = %d" % s["mtu"])
    allowed = dev.get("allowed_ips") or "0.0.0.0/0, ::/0"
    lines += ["", "[Peer]", "PublicKey = %s" % s["public_key"],
              "PresharedKey = %s" % dev["psk"],
              "Endpoint = %s" % fmt_endpoint(ep, s["port"]),
              "AllowedIPs = %s" % allowed, "PersistentKeepalive = 25"]
    del n4
    return "\n".join(lines) + "\n"


def render_firewall(st: Dict[str, Any], up: bool = True) -> str:
    """Script run by wg-quick after the interface is up (or down)."""
    s = st["server"]
    flag = "-I" if up else "-D"
    n4, n6 = s["ipv4_net"], s["ipv6_net"]
    iface = s["interface"]
    web = st["web"]
    out = ["#!/bin/sh", "# Managed by Setu.", "set -u",
           "WAN4=$(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i==\"dev\"){print $(i+1); exit}}')",
           "WAN6=$(ip -6 route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i==\"dev\"){print $(i+1); exit}}')",
           "",
           "# rule <cmd> <table> <chain> <spec...>: add once, or remove",
           "rule() {",
           "  cmd=$1; table=$2; chain=$3; shift 3",
           "  if [ \"%s\" = \"-I\" ]; then" % flag,
           "    $cmd -w -t $table -C $chain \"$@\" 2>/dev/null || $cmd -w -t $table -I $chain 1 \"$@\"",
           "  else",
           "    $cmd -w -t $table -D $chain \"$@\" 2>/dev/null || true",
           "  fi",
           "}", ""]
    for cmd, net, wan in (("iptables", n4, "WAN4"), ("ip6tables", n6, "WAN6")):
        out.append("if command -v %s >/dev/null 2>&1; then" % cmd)
        ports = ["-p udp --dport %d" % s["port"]]
        out.append("  rule %s filter INPUT -p udp --dport %d -j ACCEPT" % (cmd, s["port"]))
        out.append("  rule %s filter INPUT -i %s -p udp --dport 53 -j ACCEPT" % (cmd, iface))
        out.append("  rule %s filter INPUT -i %s -p tcp --dport 53 -j ACCEPT" % (cmd, iface))
        if web.get("enabled"):
            out.append("  rule %s filter INPUT -i %s -p tcp --dport %d -j ACCEPT" % (cmd, iface, web["port"]))
        out.append("  rule %s filter INPUT -i %s -p icmp -j ACCEPT" % (cmd, iface) if cmd == "iptables"
                   else "  rule %s filter INPUT -i %s -p ipv6-icmp -j ACCEPT" % (cmd, iface))
        # FORWARD rules are inserted at position 1, so list them last-to-first
        out.append("  rule %s filter FORWARD -o %s -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" % (cmd, iface))
        out.append("  rule %s filter FORWARD -i %s -j ACCEPT" % (cmd, iface))
        if s.get("isolate_clients", True):
            out.append("  rule %s filter FORWARD -i %s -o %s -j DROP" % (cmd, iface, iface))
        out.append("  rule %s mangle FORWARD -i %s -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu" % (cmd, iface))
        out.append("  if [ -n \"${%s:-}\" ]; then" % wan)
        out.append("    rule %s nat POSTROUTING -s %s -o \"$%s\" -j MASQUERADE" % (cmd, net, wan))
        out.append("  fi")
        out.append("fi")
        del ports
    out.append("exit 0")
    return "\n".join(out) + "\n"


def render_dnsmasq(st: Dict[str, Any], hosts_path: str, custom_path: str) -> str:
    v4, v6 = server_ips(st)
    lines = ["# Managed by Setu.", "listen-address=%s,%s" % (v4, v6), "bind-interfaces",
             "port=53", "no-resolv", "no-hosts", "domain-needed", "bogus-priv",
             "cache-size=10000", "min-cache-ttl=60", "stop-dns-rebind"]
    for srv in upstream_servers(st):
        lines.append("server=%s" % srv)
    if st["dns"].get("blocklist", "ads") != "off":
        lines.append("addn-hosts=%s" % hosts_path)
    lines.append("conf-file=%s" % custom_path)
    return "\n".join(lines) + "\n"


def render_custom_dns(st: Dict[str, Any]) -> str:
    lines = ["# Managed by Setu: your own blocked domains (`setu dns block ...`)."]
    for dom in sorted(set(st["dns"].get("block", []))):
        lines.append("address=/%s/0.0.0.0" % dom)
        lines.append("address=/%s/::" % dom)
    return "\n".join(lines) + "\n"


def parse_hosts(text: str, allow=()) -> str:
    """Turn a hosts-format blocklist into `0.0.0.0 domain` lines, minus the allowlist."""
    allowed = {a.lower() for a in allow}
    seen = set()
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2 or parts[0] not in ("0.0.0.0", "127.0.0.1"):
            continue
        for dom in parts[1:]:
            dom = dom.lower()
            if dom in ("localhost", "localhost.localdomain", "local", "broadcasthost",
                       "ip6-localhost", "ip6-loopback", "0.0.0.0") or dom in seen:
                continue
            if any(dom == a or dom.endswith("." + a) for a in allowed):
                continue
            seen.add(dom)
            out.append("0.0.0.0 " + dom)
    return "\n".join(out) + "\n"
