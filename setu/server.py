"""Server-side install, maintenance and uninstall (runs on the VPN host as root)."""
from __future__ import annotations

import os
import shutil
import urllib.request
from typing import Any, Dict, List, Optional

from . import config, system
from .state import SetuError, Store, prune, now

OPT = "/opt/setu"

UNIT_DNS = """[Unit]
Description=Setu DNS filter (dnsmasq)
After=wg-quick@{iface}.service
Requires=wg-quick@{iface}.service

[Service]
ExecStart={dnsmasq} --keep-in-foreground --conf-file={etc}/dnsmasq.conf --user=nobody
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

UNIT_WEB = """[Unit]
Description=Setu web panel (reachable only through the VPN)
After=wg-quick@{iface}.service
Requires=wg-quick@{iface}.service

[Service]
Environment=PYTHONPATH={opt}
ExecStart=/usr/bin/env python3 -m setu web --bind {bind} --port {port}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

UNIT_TIMER = """[Unit]
Description=Setu daily maintenance

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
"""

UNIT_MAINT = """[Unit]
Description=Setu maintenance (expire devices, refresh blocklist)

[Service]
Type=oneshot
Environment=PYTHONPATH={opt}
ExecStart=/usr/bin/env python3 -m setu maintenance
"""

WRAPPER = """#!/bin/sh
exec env PYTHONPATH=%s python3 -m setu "$@"
""" % OPT


def detect_os() -> str:
    try:
        text = open("/etc/os-release").read().lower()
    except OSError:
        return "unknown"
    if "debian" in text or "ubuntu" in text:
        return "apt"
    if any(x in text for x in ("fedora", "rhel", "centos", "rocky", "almalinux")):
        return "dnf"
    return "unknown"


def install_packages(runner: system.Runner, adblock: bool, harden: bool) -> None:
    mgr = detect_os()
    if mgr == "apt":
        pk = ["wireguard", "wireguard-tools", "iptables", "iproute2", "ca-certificates"]
        if adblock:
            pk.append("dnsmasq-base")
        if harden:
            pk += ["ufw", "unattended-upgrades"]
        runner.run(["apt-get", "update", "-y"], check=False)
        runner.run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"] + pk)
    elif mgr == "dnf":
        pk = ["wireguard-tools", "iptables", "iproute"]
        if adblock:
            pk.append("dnsmasq")
        runner.run(["dnf", "install", "-y"] + pk)
    else:
        raise SetuError("unsupported OS: Setu supports Debian/Ubuntu and Fedora/RHEL family. "
                        "Install wireguard-tools, iptables%s yourself and re-run with --skip-packages."
                        % (", dnsmasq" if adblock else ""))


def detect_public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                ip = r.read().decode().strip()
            if ip and len(ip) < 46:
                return ip
        except Exception:
            continue
    raise SetuError("could not detect the public IP; pass --endpoint YOUR.IP.OR.DOMAIN")


def install_self() -> None:
    """Copy this package to /opt/setu and create the `setu` command."""
    src = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(system.p(OPT), "setu")
    if os.path.abspath(src) != os.path.abspath(dst):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    system.write(system.p("/usr/local/bin/setu"), WRAPPER, 0o755)


def write_sysctl(runner: system.Runner) -> None:
    system.write(system.p("/etc/sysctl.d/99-setu.conf"),
                 "net.ipv4.ip_forward=1\nnet.ipv6.conf.all.forwarding=1\n")
    runner.run(["sysctl", "-p", system.p("/etc/sysctl.d/99-setu.conf")], check=False)


def write_units(st: Dict[str, Any], runner: system.Runner) -> None:
    from .state import server_ips
    iface = st["server"]["interface"]
    unit_dir = system.p("/etc/systemd/system")
    names: List[str] = []
    if config.uses_local_dns(st):
        dnsmasq = shutil.which("dnsmasq") or "/usr/sbin/dnsmasq"
        system.write(os.path.join(unit_dir, "setu-dns.service"),
                     UNIT_DNS.format(iface=iface, dnsmasq=dnsmasq, etc=system.ETC))
        names.append("setu-dns.service")
    if st["web"].get("enabled"):
        v4, _ = server_ips(st)
        system.write(os.path.join(unit_dir, "setu-web.service"),
                     UNIT_WEB.format(iface=iface, opt=OPT, bind=v4, port=st["web"]["port"]))
        names.append("setu-web.service")
    system.write(os.path.join(unit_dir, "setu-maintenance.service"), UNIT_MAINT.format(opt=OPT))
    system.write(os.path.join(unit_dir, "setu-maintenance.timer"), UNIT_TIMER)
    runner.run(["systemctl", "daemon-reload"])
    runner.run(["systemctl", "enable", "--now", "setu-maintenance.timer"], check=False)
    for n in names:
        runner.run(["systemctl", "enable", n], check=False)
        runner.run(["systemctl", "restart", n], check=False)


def harden(st: Dict[str, Any], runner: system.Runner) -> None:
    """Basic host firewall: SSH + the WireGuard port only; unattended security updates."""
    runner.run(["ufw", "allow", "22/tcp"], check=False)
    runner.run(["ufw", "allow", "%d/udp" % st["server"]["port"]], check=False)
    runner.run(["ufw", "--force", "enable"], check=False)
    if detect_os() == "apt":
        system.write(system.p("/etc/apt/apt.conf.d/20auto-upgrades"),
                     'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n')


def update_blocklist(st: Dict[str, Any], runner: system.Runner, fetch=None) -> int:
    """Download the chosen blocklist, apply allowlist, restart DNS. Returns domain count."""
    name = st["dns"].get("blocklist", "ads")
    hosts = os.path.join(system.ETC, "blocklist.hosts")
    if name == "off" or not config.uses_local_dns(st):
        system.write(hosts, "")
        return 0
    url = config.BLOCKLISTS.get(name) or name  # a custom URL is allowed
    if fetch is None:
        def fetch(u: str) -> str:
            req = urllib.request.Request(u, headers={"User-Agent": "setu"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
    text = config.parse_hosts(fetch(url), st["dns"].get("allow", []))
    if not text.strip():
        raise SetuError("blocklist from %s was empty; keeping the old one" % url)
    system.write(hosts, text)
    runner.run(["systemctl", "restart", "setu-dns.service"], check=False)
    return text.count("\n")


def init(st: Dict[str, Any], store: Store, runner: system.Runner, harden_host: bool = False,
         skip_packages: bool = False, fetch=None, log=print) -> Dict[str, Any]:
    """Install everything for the given state and bring the VPN up."""
    if os.geteuid() != 0 and not runner.dry_run and system.ROOT == "/":
        raise SetuError("run as root (sudo)")
    if st["server"]["endpoint"] in ("", "auto"):
        st["server"]["endpoint"] = detect_public_ip() if not runner.dry_run else "203.0.113.10"
    adblock = config.uses_local_dns(st)
    if not skip_packages:
        log("Installing packages...")
        install_packages(runner, adblock, harden_host)
    log("Installing Setu...")
    install_self()
    write_sysctl(runner)
    store.save(st)
    system.apply(st, runner, reload=False)
    if harden_host:
        harden(st, runner)
    runner.run(["systemctl", "enable", "--now", "wg-quick@%s" % st["server"]["interface"]])
    write_units(st, runner)
    if adblock and st["dns"].get("blocklist", "ads") != "off":
        log("Downloading blocklist...")
        try:
            update_blocklist(st, runner, fetch)
        except Exception as e:  # not fatal: VPN works, run `setu dns update` later
            log("  blocklist download failed (%s); run `setu dns update` later" % e)
    return st


def maintenance(store: Store, runner: system.Runner, fetch=None) -> List[str]:
    """Daily job: remove expired devices, refresh blocklist."""
    with store.locked():
        st = store.load()
        gone = prune(st, None)
        if gone:
            store.save(st)
            system.apply(st, runner)
    try:
        update_blocklist(store.load(), runner, fetch)
    except Exception:
        pass
    return gone


def uninstall(st: Optional[Dict[str, Any]], runner: system.Runner, purge: bool = False) -> None:
    iface = (st or {}).get("server", {}).get("interface", "wg0")
    for unit in ("setu-web.service", "setu-dns.service", "setu-maintenance.timer"):
        runner.run(["systemctl", "disable", "--now", unit], check=False)
    runner.run(["systemctl", "disable", "--now", "wg-quick@%s" % iface], check=False)
    for f in ("/etc/systemd/system/setu-web.service", "/etc/systemd/system/setu-dns.service",
              "/etc/systemd/system/setu-maintenance.service", "/etc/systemd/system/setu-maintenance.timer",
              "/etc/sysctl.d/99-setu.conf", "/usr/local/bin/setu",
              "/etc/wireguard/%s.conf" % iface):
        try:
            os.remove(system.p(f))
        except FileNotFoundError:
            pass
    shutil.rmtree(system.p(OPT), ignore_errors=True)
    runner.run(["systemctl", "daemon-reload"], check=False)
    if purge:
        shutil.rmtree(system.ETC, ignore_errors=True)
