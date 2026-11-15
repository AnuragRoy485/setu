"""Server state: one JSON file is the source of truth for everything."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
from typing import Any, Dict, Optional

from . import crypto

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class SetuError(Exception):
    """A problem the user can fix; printed without a traceback."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def new_state(endpoint: str = "auto", port: int = 51820, dns: str = "adblock",
              upstream: str = "cloudflare", blocklist: str = "ads",
              ipv4_net: str = "10.66.66.0/24", ipv6_net: str = "fd66:66:66::/64",
              mtu: Optional[int] = None, isolate_clients: bool = True,
              web_port: int = 8080) -> Dict[str, Any]:
    ipaddress.ip_network(ipv4_net)
    ipaddress.ip_network(ipv6_net)
    if not 1 <= int(port) <= 65535:
        raise SetuError("port must be 1-65535")
    priv = crypto.genkey()
    return {
        "version": 1,
        "created": now(),
        "server": {
            "private_key": priv, "public_key": crypto.pubkey(priv),
            "endpoint": endpoint, "port": int(port), "interface": "wg0",
            "ipv4_net": ipv4_net, "ipv6_net": ipv6_net, "mtu": mtu,
            "isolate_clients": isolate_clients,
        },
        "dns": {"mode": dns, "upstream": upstream, "custom": [], "blocklist": blocklist,
                "allow": [], "block": []},
        "web": {"enabled": True, "port": int(web_port), "token_sha256": None},
        "devices": {},
    }


def server_ips(st: Dict[str, Any]):
    v4 = ipaddress.ip_network(st["server"]["ipv4_net"])
    v6 = ipaddress.ip_network(st["server"]["ipv6_net"])
    return next(v4.hosts()), next(v6.hosts())


def set_web_token(st: Dict[str, Any], token: Optional[str] = None) -> str:
    token = token or secrets.token_urlsafe(24)
    st["web"]["token_sha256"] = hashlib.sha256(token.encode()).hexdigest()
    return token


def check_web_token(st: Dict[str, Any], token: str) -> bool:
    want = st["web"].get("token_sha256")
    if not want or not token:
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), want)


def _next_ips(st: Dict[str, Any]):
    v4 = ipaddress.ip_network(st["server"]["ipv4_net"])
    v6 = ipaddress.ip_network(st["server"]["ipv6_net"])
    used = {d["ipv4"] for d in st["devices"].values()}
    for i, host in enumerate(v4.hosts()):
        if i == 0:
            continue  # server
        if str(host) not in used:
            return str(host), str(v6.network_address + int(host) - int(v4.network_address))
    raise SetuError("no free addresses left in %s" % v4)


def add_device(st: Dict[str, Any], name: str, public_key: Optional[str] = None,
               expires_days: Optional[float] = None, allowed_ips: Optional[str] = None,
               user: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    name = name.strip().lower()
    if not NAME_RE.match(name):
        raise SetuError("name must be 1-32 chars: a-z, 0-9, '-' or '_' (got %r)" % name)
    if name in st["devices"]:
        raise SetuError("device %r already exists" % name)
    v4, v6 = _next_ips(st)
    dev: Dict[str, Any] = {"name": name, "user": user or name.split("-")[0].split("_")[0],
                           "ipv4": v4, "ipv6": v6, "psk": crypto.genpsk(), "enabled": True,
                           "created": now(), "expires": None, "allowed_ips": allowed_ips,
                           "note": note}
    if public_key:
        if not crypto.valid_key(public_key):
            raise SetuError("that is not a valid WireGuard public key")
        dev["public_key"] = public_key.strip()
        dev["private_key"] = None
    else:
        dev["private_key"] = crypto.genkey()
        dev["public_key"] = crypto.pubkey(dev["private_key"])
    if expires_days:
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=float(expires_days))
        dev["expires"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    if allowed_ips:
        for part in allowed_ips.split(","):
            ipaddress.ip_network(part.strip(), strict=False)
    st["devices"][name] = dev
    return dev


def remove_device(st: Dict[str, Any], name: str) -> None:
    if name not in st["devices"]:
        raise SetuError("no device called %r" % name)
    del st["devices"][name]


def expired(dev: Dict[str, Any], at: Optional[dt.datetime] = None) -> bool:
    if not dev.get("expires"):
        return False
    return parse_time(dev["expires"]) <= (at or dt.datetime.now(dt.timezone.utc))


def prune(st: Dict[str, Any], at: Optional[dt.datetime] = None):
    gone = [n for n, d in st["devices"].items() if expired(d, at)]
    for n in gone:
        del st["devices"][n]
    return gone


class Store:
    """Locked, atomic access to the state file."""

    def __init__(self, path: str):
        self.path = path

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            raise SetuError("no Setu server found at %s - run `setu server init` first" % self.path)

    def save(self, st: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(st, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    @contextlib.contextmanager
    def locked(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        with open(self.path + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            yield
