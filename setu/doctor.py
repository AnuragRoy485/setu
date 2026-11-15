"""Health checks: `setu doctor`."""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

from . import config, system
from .state import server_ips

Check = Tuple[str, bool, str]  # name, ok, hint


def run_checks(st: Dict[str, Any], runner: system.Runner) -> List[Check]:
    s = st["server"]
    iface = s["interface"]
    out: List[Check] = []

    def add(name: str, ok: bool, hint: str = "") -> None:
        out.append((name, bool(ok), "" if ok else hint))

    add("WireGuard tools installed", system.have("wg"), "install wireguard-tools")
    up = runner.run(["ip", "link", "show", iface], check=False).returncode == 0
    add("Interface %s is up" % iface, up, "systemctl restart wg-quick@%s" % iface)
    try:
        v4 = open("/proc/sys/net/ipv4/ip_forward").read().strip() == "1"
    except OSError:
        v4 = False
    add("IPv4 forwarding enabled", v4, "sysctl -w net.ipv4.ip_forward=1")
    listening = runner.run(["wg", "show", iface, "listen-port"], check=False)
    add("Listening on UDP %d" % s["port"], listening.stdout.strip() == str(s["port"]),
        "open UDP %d in your cloud firewall / security group" % s["port"])
    rules = runner.run(["iptables", "-t", "nat", "-S", "POSTROUTING"], check=False).stdout
    add("NAT (masquerade) rule present", "MASQUERADE" in rules and s["ipv4_net"] in rules,
        "systemctl restart wg-quick@%s" % iface)
    if config.uses_local_dns(st):
        active = runner.run(["systemctl", "is-active", "setu-dns.service"], check=False)
        add("DNS filter (setu-dns) running", active.stdout.strip() == "active",
            "journalctl -u setu-dns -n 30")
        hosts = os.path.join(system.ETC, "blocklist.hosts")
        n = 0
        if os.path.exists(hosts):
            with open(hosts) as f:
                n = sum(1 for _ in f)
        add("Blocklist loaded (%d domains)" % n, n > 0 or st["dns"]["blocklist"] == "off",
            "run `setu dns update`")
    # IPv6: informational, since many cheap servers have no IPv6 at all
    has_v6 = runner.run(["ip", "-6", "route", "show", "default"], check=False).stdout.strip() != ""
    if has_v6:
        r6 = runner.run(["ip6tables", "-t", "nat", "-S", "POSTROUTING"], check=False).stdout
        add("IPv6 NAT (masquerade) rule present", "MASQUERADE" in r6 and s["ipv6_net"] in r6,
            "systemctl restart wg-quick@%s" % iface)
    else:
        out.append(("Server has no IPv6 route: devices use IPv4 only (this is fine)", True, ""))
    free = system.disk_free_pct("/")
    add("Disk space (%d%% free)" % free, free >= 10, "free up disk space: journalctl --vacuum-size=50M")
    peers = system.wg_dump(st, runner)
    live = [d for d in st["devices"].values() if d["public_key"] in peers
            and peers[d["public_key"]]["handshake"] > 0
            and time.time() - peers[d["public_key"]]["handshake"] < 300]
    out.append(("Devices connected in the last 5 min: %d of %d" % (len(live), len(st["devices"])),
                True, ""))
    web = st["web"]
    if web.get("enabled"):
        v4ip, _ = server_ips(st)
        out.append(("Web panel (VPN only): http://%s:%d" % (v4ip, web["port"]), True, ""))
    return out


def format_checks(checks: List[Check]) -> str:
    lines = []
    for name, ok, hint in checks:
        lines.append("  %s %s%s" % ("OK  " if ok else "FAIL", name, "  -> " + hint if hint else ""))
    return "\n".join(lines)


def summary(st: Dict[str, Any], runner: system.Runner) -> Dict[str, Any]:
    """Machine-readable health for the web panel and `setu health --json`."""
    checks = run_checks(st, runner)
    bad = [c for c in checks if not c[1]]
    return {"ok": not bad,
            "checks": [{"name": n, "ok": ok, "hint": h} for n, ok, h in checks],
            "system": system.stats()}
