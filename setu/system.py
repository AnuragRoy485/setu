"""Everything that touches the host: writing files, running commands, applying state."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from . import config
from .state import SetuError, Store

ETC = os.environ.get("SETU_DIR", "/etc/setu")
ROOT = os.environ.get("SETU_ROOT", "/")  # prefix for everything outside SETU_DIR (tests)


def p(path: str) -> str:
    """Map an absolute system path under SETU_ROOT."""
    return os.path.join(ROOT, path.lstrip("/")) if ROOT != "/" else path


class Runner:
    """Runs commands; in dry-run mode records them instead (used by the tests)."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.log: List[List[str]] = []

    def run(self, cmd: List[str], check: bool = True, input: Optional[str] = None) -> subprocess.CompletedProcess:
        self.log.append(cmd)
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            res = subprocess.run(cmd, input=input, capture_output=True, text=True)
        except OSError:
            if not check:
                return subprocess.CompletedProcess(cmd, 127, "", "command not found")
            raise SetuError("command not found: %s" % cmd[0])
        if check and res.returncode != 0:
            raise SetuError("`%s` failed: %s" % (" ".join(cmd), (res.stderr or res.stdout).strip()))
        return res


def write(path: str, text: str, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def wg_conf_path(st: Dict[str, Any]) -> str:
    return p("/etc/wireguard/%s.conf" % st["server"]["interface"])


def render_files(st: Dict[str, Any]) -> None:
    """Write all generated config files for the current state."""
    write(wg_conf_path(st), config.render_server_conf(st), 0o600)
    write(os.path.join(ETC, "postup.sh"), config.render_firewall(st, True), 0o755)
    write(os.path.join(ETC, "postdown.sh"), config.render_firewall(st, False), 0o755)
    if config.uses_local_dns(st):
        write(os.path.join(ETC, "dnsmasq.conf"),
              config.render_dnsmasq(st, os.path.join(ETC, "blocklist.hosts"),
                                    os.path.join(ETC, "custom-dns.conf")), 0o644)
        write(os.path.join(ETC, "custom-dns.conf"), config.render_custom_dns(st), 0o644)
        hosts = os.path.join(ETC, "blocklist.hosts")
        if not os.path.exists(hosts):
            write(hosts, "", 0o644)


def reload_wireguard(st: Dict[str, Any], runner: Runner) -> None:
    """Apply peers to a running interface without dropping existing connections."""
    iface = st["server"]["interface"]
    up = runner.run(["ip", "link", "show", iface], check=False).returncode == 0
    if not up:
        runner.run(["systemctl", "enable", "--now", "wg-quick@%s" % iface])
        return
    stripped = runner.run(["wg-quick", "strip", iface])
    runner.run(["wg", "syncconf", iface, "/dev/stdin"], input=stripped.stdout)


def restart_dns(st: Dict[str, Any], runner: Runner) -> None:
    if config.uses_local_dns(st):
        runner.run(["systemctl", "restart", "setu-dns.service"], check=False)


def apply(st: Dict[str, Any], runner: Runner, reload: bool = True) -> None:
    render_files(st)
    if reload:
        reload_wireguard(st, runner)


def wg_dump(st: Dict[str, Any], runner: Runner) -> Dict[str, Dict[str, Any]]:
    """Live peer stats keyed by public key (empty if the interface is down)."""
    res = runner.run(["wg", "show", st["server"]["interface"], "dump"], check=False)
    out: Dict[str, Dict[str, Any]] = {}
    if res.returncode != 0:
        return out
    for line in res.stdout.strip().splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 7:
            out[f[0]] = {"endpoint": None if f[2] == "(none)" else f[2],
                         "handshake": int(f[4]), "rx": int(f[5]), "tx": int(f[6])}
    return out


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def load_store(path: Optional[str] = None) -> Store:
    return Store(path or os.path.join(ETC, "state.json"))
