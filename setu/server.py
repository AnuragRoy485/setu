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

OPENRC_WG = """#!/sbin/openrc-run
description="Setu WireGuard ({iface})"

depend() {{
    need net
}}

start() {{
    ebegin "Starting {iface}"
    ip link show {iface} >/dev/null 2>&1 || wg-quick up {iface}
    eend $?
}}

stop() {{
    ebegin "Stopping {iface}"
    wg-quick down {iface}
    eend $?
}}
"""

OPENRC_SVC = """#!/sbin/openrc-run
description="{desc}"
supervisor="supervise-daemon"
command="{cmd}"
command_args="{args}"

depend() {{
    need net setu-wg
}}
"""

CRON_MAINT = """#!/bin/sh
exec env PYTHONPATH=%s python3 -m setu maintenance
""" % OPT


def detect_os() -> str:
    text = ""
    for rel in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(system.p(rel)) as f:
                text = f.read()
            break
        except OSError:
            continue
    if not text:
        return "unknown"
    kv: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip().lower()] = v.strip().strip('"').strip("'").lower()
    ids = set((kv.get("id", "") + " " + kv.get("id_like", "")).split())
    if ids & {"debian", "ubuntu"}:
        return "apt"
    if ids & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
        return "dnf"
    if "alpine" in ids:
        return "apk"
    if ids & {"arch", "archarm"}:
        return "pacman"
    return "unknown"


def is_openrc() -> bool:
    mgr = detect_os()
    if mgr == "apk":
        return True
    if mgr in ("apt", "dnf", "pacman"):
        return False
    return os.path.exists(system.p("/sbin/openrc-run"))


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
    elif mgr == "apk":
        pk = ["wireguard-tools", "iptables", "ip6tables", "iproute2", "ca-certificates"]
        if adblock:
            pk.append("dnsmasq")
        runner.run(["apk", "add", "--no-cache"] + pk)
        if harden:
            runner.run(["apk", "add", "--no-cache", "ufw"], check=False)
    elif mgr == "pacman":
        pk = ["wireguard-tools", "iptables", "iproute2", "ca-certificates"]
        if adblock:
            pk.append("dnsmasq")
        if harden:
            pk.append("ufw")
        runner.run(["pacman", "-Sy", "--noconfirm", "--needed"] + pk)
    else:
        raise SetuError("unsupported OS: Setu supports Debian/Ubuntu, Fedora/RHEL, Alpine and Arch Linux. "
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


def write_openrc(st: Dict[str, Any], runner: system.Runner) -> None:
    from .state import server_ips
    iface = st["server"]["interface"]
    init_dir = system.p("/etc/init.d")
    system.write(os.path.join(init_dir, "setu-wg"), OPENRC_WG.format(iface=iface), 0o755)
    runner.run(["rc-update", "add", "setu-wg", "default"], check=False)
    runner.run(["rc-service", "setu-wg", "restart"])
    names: List[str] = []
    if config.uses_local_dns(st):
        dnsmasq = shutil.which("dnsmasq") or "/usr/sbin/dnsmasq"
        system.write(os.path.join(init_dir, "setu-dns"),
                     OPENRC_SVC.format(desc="Setu DNS filter (dnsmasq)", cmd=dnsmasq,
                                       args="--keep-in-foreground --conf-file=%s/dnsmasq.conf --user=nobody" % system.ETC),
                     0o755)
        names.append("setu-dns")
    if st["web"].get("enabled"):
        v4, _ = server_ips(st)
        system.write(os.path.join(init_dir, "setu-web"),
                     OPENRC_SVC.format(desc="Setu web panel (reachable only through the VPN)",
                                       cmd="/usr/local/bin/setu",
                                       args="web --bind %s --port %d" % (v4, st["web"]["port"])),
                     0o755)
        names.append("setu-web")
    system.write(system.p("/etc/periodic/daily/setu-maintenance"), CRON_MAINT, 0o755)
    runner.run(["rc-update", "add", "crond", "default"], check=False)
    runner.run(["rc-service", "crond", "start"], check=False)
    for n in names:
        runner.run(["rc-update", "add", n, "default"], check=False)
        runner.run(["rc-service", n, "restart"], check=False)


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
    system.restart_dns(st, runner)
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
    if is_openrc():
        write_openrc(st, runner)
    else:
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
    openrc = is_openrc()
    if openrc:
        for unit in ("setu-web", "setu-dns", "setu-wg"):
            runner.run(["rc-service", unit, "stop"], check=False)
            runner.run(["rc-update", "del", unit, "default"], check=False)
    else:
        for unit in ("setu-web.service", "setu-dns.service", "setu-maintenance.timer"):
            runner.run(["systemctl", "disable", "--now", unit], check=False)
        runner.run(["systemctl", "disable", "--now", "wg-quick@%s" % iface], check=False)
    for f in ("/etc/systemd/system/setu-web.service", "/etc/systemd/system/setu-dns.service",
              "/etc/systemd/system/setu-maintenance.service", "/etc/systemd/system/setu-maintenance.timer",
              "/etc/init.d/setu-web", "/etc/init.d/setu-dns", "/etc/init.d/setu-wg",
              "/etc/periodic/daily/setu-maintenance",
              "/etc/sysctl.d/99-setu.conf", "/usr/local/bin/setu",
              "/etc/wireguard/%s.conf" % iface):
        try:
            os.remove(system.p(f))
        except FileNotFoundError:
            pass
    shutil.rmtree(system.p(OPT), ignore_errors=True)
    if not openrc:
        runner.run(["systemctl", "daemon-reload"], check=False)
    if purge:
        shutil.rmtree(system.ETC, ignore_errors=True)
