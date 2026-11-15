"""Command line interface."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import io
import time
from typing import Any, Dict, List, Optional

from . import __version__, card, cloudinit, config, crypto, doctor, providers, qr, server, system, usage
from . import state as S
from .state import SetuError

DNS_CHOICES = ["adblock"] + list(config.DNS_PRESETS)


def store_for(args) -> S.Store:
    return system.load_store(getattr(args, "state", None))


def show_qr(text: str) -> None:
    try:
        print(qr.to_terminal(qr.make(text, "L")))
    except ValueError:
        print("(config too long for a QR code - use the .conf file)")


def save_config(st: Dict[str, Any], dev: Dict[str, Any], out: Optional[str], png: Optional[str]) -> None:
    text = config.render_client_conf(st, dev)
    if out:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        print("Saved %s" % out)
    if png:
        with open(png, "wb") as f:
            f.write(qr.to_png(qr.make(text, "L")))
        print("Saved %s" % png)


# --- commands ---------------------------------------------------------------------
def cmd_server_init(args) -> int:
    store = store_for(args)
    runner = system.Runner(args.dry_run)
    if args.state_file:
        raw = sys.stdin.read() if args.state_file == "-" else open(args.state_file).read()
        st = json.loads(raw)
        first = None
    else:
        if store.exists() and not args.force:
            raise SetuError("a Setu server is already set up here. Use `setu add` to add devices "
                            "(or --force to start over, which invalidates every device).")
        st = S.new_state(args.endpoint or "auto", args.port, args.dns, args.upstream, args.blocklist,
                         args.ipv4_net, args.ipv6_net, args.mtu, not args.allow_device_traffic, args.web_port)
        st["web"]["enabled"] = not args.no_web
        first = S.add_device(st, args.first_device)
    token = None
    if not st["web"].get("token_sha256"):
        token = S.set_web_token(st)
    server.init(st, store, runner, args.harden, args.skip_packages)
    store.save(st)
    system.apply(st, runner)
    print("\nSetu is running.\n")
    if first:
        text = config.render_client_conf(st, first)
        print("Scan this with the WireGuard app (device: %s):\n" % first["name"])
        show_qr(text)
        print()
    v4, _ = S.server_ips(st)
    if st["web"]["enabled"]:
        print("Web panel (open it after connecting the VPN): http://%s:%d" % (v4, st["web"]["port"]))
        if token:
            print("Admin token (shown once): %s" % token)
    print("Add more devices:  sudo setu add alice-laptop")
    return 0


def cmd_add(args) -> int:
    store = store_for(args)
    runner = system.Runner(args.dry_run)
    with store.locked():
        st = store.load()
        dev = S.add_device(st, args.name, args.public_key, args.expires, args.split)
        store.save(st)
        system.apply(st, runner)
    print("Added %s (%s)" % (dev["name"], dev["ipv4"]))
    text = config.render_client_conf(st, dev)
    save_config(st, dev, args.out, args.png)
    if not args.no_qr:
        print("\nScan with the WireGuard app:\n")
        show_qr(text)
    if args.show_config or args.public_key:
        print("\n" + text)
    return 0


def cmd_remove(args) -> int:
    store = store_for(args)
    with store.locked():
        st = store.load()
        S.remove_device(st, args.name)
        store.save(st)
        system.apply(st, system.Runner(args.dry_run))
    print("Removed %s. Its config stops working now." % args.name)
    return 0


def cmd_toggle(args, enable: bool) -> int:
    store = store_for(args)
    with store.locked():
        st = store.load()
        if args.name not in st["devices"]:
            raise SetuError("no device called %r" % args.name)
        st["devices"][args.name]["enabled"] = enable
        store.save(st)
        system.apply(st, system.Runner(args.dry_run))
    print("%s %s" % ("Resumed" if enable else "Paused", args.name))
    return 0


def cmd_list(args) -> int:
    store = store_for(args)
    st = store.load()
    runner = system.Runner(getattr(args, 'dry_run', False))
    peers = system.wg_dump(st, runner)
    if args.json:
        from .web import device_view
        print(json.dumps([device_view(d, peers) for d in st["devices"].values()], indent=2))
        return 0
    if not st["devices"]:
        print("No devices yet. Try: sudo setu add my-phone")
        return 0
    print("%-20s %-14s %-11s %-10s %s" % ("DEVICE", "IP", "STATE", "LAST SEEN", "EXPIRES"))
    for d in st["devices"].values():
        p = peers.get(d["public_key"], {})
        hs = p.get("handshake", 0)
        seen = "never" if not hs else "%ds ago" % max(0, int(time.time() - hs))
        state = "paused" if not d.get("enabled", True) else ("online" if hs and time.time() - hs < 180 else "idle")
        print("%-20s %-14s %-11s %-10s %s" % (d["name"], d["ipv4"], state, seen, (d.get("expires") or "-")[:10]))
    return 0


def cmd_show(args, as_qr: bool) -> int:
    st = store_for(args).load()
    if args.name not in st["devices"]:
        raise SetuError("no device called %r (see `setu list`)" % args.name)
    dev = st["devices"][args.name]
    if not dev.get("private_key"):
        raise SetuError("%s was added with its own key, so its private key is not stored" % args.name)
    text = config.render_client_conf(st, dev)
    save_config(st, dev, getattr(args, "out", None), getattr(args, "png", None))
    if as_qr:
        show_qr(text)
    else:
        print(text, end="")
    return 0


def cmd_status(args) -> int:
    st = store_for(args).load()
    s = st["server"]
    print("Setu %s" % __version__)
    print("Endpoint : %s" % config.fmt_endpoint(s["endpoint"], s["port"]))
    print("DNS      : %s%s" % (st["dns"]["mode"], " (blocklist: %s)" % st["dns"]["blocklist"] if config.uses_local_dns(st) else ""))
    print("Devices  : %d" % len(st["devices"]))
    return cmd_list(args)


def cmd_doctor(args) -> int:
    st = store_for(args).load()
    checks = doctor.run_checks(st, system.Runner(args.dry_run))
    print(doctor.format_checks(checks))
    bad = [c for c in checks if not c[1]]
    print("\n%s" % ("All good." if not bad else "%d problem(s) found." % len(bad)))
    return 1 if bad else 0


def cmd_health(args) -> int:
    st = store_for(args).load()
    res = doctor.summary(st, system.Runner(args.dry_run))
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(doctor.format_checks([(c["name"], c["ok"], c["hint"]) for c in res["checks"]]))
        sy = res["system"]
        print("\nuptime %s, load %s, memory used %s%%, disk free %s%%" % (
            "%dd %dh" % (sy["uptime_s"] // 86400, sy["uptime_s"] % 86400 // 3600) if sy["uptime_s"] is not None else "?",
            " ".join("%.2f" % x for x in sy["load"]) if sy["load"] else "?",
            sy["mem_used_pct"] if sy["mem_used_pct"] is not None else "?", sy["disk_free_pct"]))
    return 0 if res["ok"] else 1


def cmd_sample(args) -> int:
    store = store_for(args)
    usage.sample(store.load(), system.Runner(args.dry_run))
    return 0


def _fmt_bytes(n: int) -> str:
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= div:
            return "%.1f %s" % (n / div, unit)
    return "%d B" % n


def cmd_usage(args) -> int:
    st = store_for(args).load()
    names = [args.name] if args.name else list(st["devices"])
    for n in names:
        if n not in st["devices"]:
            raise SetuError("no device called %r (see `setu list`)" % n)
    data = usage.load()
    ov = usage.overview(data, names, args.days)
    if args.json:
        print(json.dumps(ov, indent=2))
        return 0
    if not names:
        print("No devices yet.")
        return 0
    print("%-20s %12s %12s   (last %d days)" % ("DEVICE", "DOWNLOADED", "UPLOADED", args.days))
    for n in names:
        sr = ov["devices"][n]
        print("%-20s %12s %12s" % (n, _fmt_bytes(sr["total_rx"]), _fmt_bytes(sr["total_tx"])))
    if not data["devices"]:
        print("\nNo history yet: the sampler runs every 5 minutes once the server is set up.")
    return 0


def cmd_card(args) -> int:
    st = store_for(args).load()
    if args.name not in st["devices"]:
        raise SetuError("no device called %r (see `setu list`)" % args.name)
    dev = st["devices"][args.name]
    if not dev.get("private_key"):
        raise SetuError("%s was added with its own key, so there is nothing to put on a card" % args.name)
    out = args.out or "%s-card.html" % args.name
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(card.render(st, dev, args.lang))
    print("Saved %s. It contains the device key: send it privately and delete it afterwards." % out)
    return 0


def cmd_expire(args) -> int:
    store = store_for(args)
    runner = system.Runner(args.dry_run)
    days = None if args.days.lower() in ("never", "none", "0") else args.days
    with store.locked():
        st = store.load()
        when = S.set_expiry(st, args.name, days)
        store.save(st)
        system.apply(st, runner)
    print("%s %s" % (args.name, "will expire at %s" % when if when else "will not expire"))
    return 0


def cmd_web(args) -> int:
    store = store_for(args)
    st = store.load()
    bind = args.bind or str(S.server_ips(st)[0])
    port = args.port or st["web"]["port"]
    srv = server_mod_web(store, bind, port)
    print("Setu panel on http://%s:%d" % (bind, port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def server_mod_web(store, bind, port):
    from . import web
    return web.serve(store, system.Runner(), bind, port)


def cmd_token(args) -> int:
    store = store_for(args)
    with store.locked():
        st = store.load()
        token = S.set_web_token(st)
        store.save(st)
    print("New admin token (shown once): %s" % token)
    return 0


def cmd_dns(args) -> int:
    store = store_for(args)
    runner = system.Runner(args.dry_run)
    with store.locked():
        st = store.load()
        d = st["dns"]
        if args.dns_cmd == "update":
            n = server.update_blocklist(st, runner)
            print("Blocklist updated: %d domains" % n)
            return 0
        if args.dns_cmd == "block":
            d["block"] = sorted(set(d.get("block", [])) | {args.domain.lower()})
        elif args.dns_cmd == "unblock":
            d["block"] = [x for x in d.get("block", []) if x != args.domain.lower()]
        elif args.dns_cmd == "allow":
            d["allow"] = sorted(set(d.get("allow", [])) | {args.domain.lower()})
        elif args.dns_cmd == "disallow":
            d["allow"] = [x for x in d.get("allow", []) if x != args.domain.lower()]
        elif args.dns_cmd == "list":
            print("blocked by you:", ", ".join(d.get("block", [])) or "-")
            print("always allowed:", ", ".join(d.get("allow", [])) or "-")
            return 0
        store.save(st)
        system.render_files(st)
        if args.dns_cmd in ("allow", "disallow"):
            server.update_blocklist(st, runner)
        else:
            system.restart_dns(st, runner)
    print("Done.")
    return 0


def cmd_maintenance(args) -> int:
    gone = server.maintenance(store_for(args), system.Runner(args.dry_run))
    for n in gone:
        print("expired and removed: %s" % n)
    return 0


def cmd_uninstall(args) -> int:
    store = store_for(args)
    st = store.load() if store.exists() else None
    if not args.yes:
        ans = input("Remove Setu, the VPN interface and its services from this server? [y/N] ")
        if ans.strip().lower() != "y":
            print("Cancelled.")
            return 1
    server.uninstall(st, system.Runner(args.dry_run), purge=args.purge)
    print("Setu removed.%s" % ("" if args.purge else " Your devices and keys are kept in %s (use --purge to delete them)." % system.ETC))
    return 0


# --- deploy -----------------------------------------------------------------------
DEPLOY_FILE = os.path.join(os.path.expanduser("~"), ".config", "setu", "deployments.json")


def _remember(rec: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DEPLOY_FILE), exist_ok=True)
    try:
        data = json.load(open(DEPLOY_FILE))
    except (OSError, ValueError):
        data = []
    data.append(rec)
    fd = os.open(DEPLOY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)


def _fresh_state(args):
    st = S.new_state("auto", args.port, args.dns, args.upstream, args.blocklist, mtu=args.mtu)
    first = S.add_device(st, args.first_device)
    token = S.set_web_token(st)
    return st, first, token


def _finish_deploy(args, st, first, token, ip: str) -> None:
    st["server"]["endpoint"] = ip
    outdir = os.path.abspath(args.out_dir)
    os.makedirs(outdir, mode=0o700, exist_ok=True)
    text = config.render_client_conf(st, first)
    conf = os.path.join(outdir, "%s.conf" % first["name"])
    fd = os.open(conf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    with open(os.path.join(outdir, "%s.png" % first["name"]), "wb") as f:
        f.write(qr.to_png(qr.make(text, "L")))
    cardfile = os.path.join(outdir, "%s-card.html" % first["name"])
    fd = os.open(cardfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(card.render(st, first, "en"))
    tokfile = os.path.join(outdir, "admin-token.txt")
    fd = os.open(tokfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    v4, _ = S.server_ips(st)
    print("\nYour server is at %s. Scan this with the WireGuard app:\n" % ip)
    show_qr(text)
    print("\nSaved in %s: %s.conf, %s.png, %s-card.html (a page you can send to the device's owner), admin-token.txt"
          % (outdir, first["name"], first["name"], first["name"]))
    print("The server needs about 2-3 minutes to finish installing; connect after that.")
    print("Web panel (while connected): http://%s:%d   (token in admin-token.txt)" % (v4, st["web"]["port"]))


def cmd_deploy(args) -> int:
    if args.target == "ssh":
        return deploy_ssh(args)
    cls = providers.PROVIDERS.get(args.target)
    if cls is None:
        raise SetuError("unknown target %r. Choose: %s, ssh" % (args.target, ", ".join(providers.PROVIDERS)))
    token = args.token or os.environ.get(cls.token_env, "")
    prov = providers.get(args.target, token)
    st, first, tok = _fresh_state(args)
    key_id = None
    if args.ssh_key:
        pub = open(os.path.expanduser(args.ssh_key)).read().strip()
        key_id = prov.ensure_ssh_key("setu-" + args.name, pub)
    ud = cloudinit.build(st, args.ref, harden=True, ssh_key_given=bool(key_id))
    region = args.region or prov.default_region
    print("Creating %s server %r in %s ..." % (args.target, args.name, region))
    res = prov.create(args.name, region, args.size, ud, key_id)
    _remember({"name": args.name, "provider": args.target, "id": res["id"], "ip": res["ip"],
               "created": S.now()})
    _finish_deploy(args, st, first, tok, res["ip"])
    print("To delete it later:  setu destroy %s %s" % (args.target, res["id"]))
    return 0


def _ssh(host: str, remote: List[str], stdin: Optional[bytes] = None, tty: bool = False) -> int:
    cmd = ["ssh"] + (["-t"] if tty else []) + ["-o", "StrictHostKeyChecking=accept-new", host] + remote
    return subprocess.run(cmd, input=stdin).returncode


def deploy_ssh(args) -> int:
    host = args.host
    if not host:
        raise SetuError("usage: setu deploy ssh --host root@1.2.3.4 (any Ubuntu/Debian/Fedora server you can SSH into)")
    st, first, tok = _fresh_state(args)
    st["server"]["endpoint"] = host.split("@")[-1]
    sudo = [] if host.startswith("root@") else ["sudo"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(os.path.dirname(os.path.abspath(__file__)), arcname="setu",
               filter=lambda ti: None if "__pycache__" in ti.name else ti)
    print("Copying Setu to %s ..." % host)
    if _ssh(host, sudo + ["mkdir", "-p", "/opt/setu", "&&"] + sudo + ["tar", "xzf", "-", "-C", "/opt/setu"], buf.getvalue()):
        raise SetuError("could not copy files over SSH")
    print("Installing (this takes a minute) ...")
    cmd = sudo + ["env", "PYTHONPATH=/opt/setu", "python3", "-m", "setu", "server", "init", "--state-file", "-"]
    if args.harden:
        cmd.append("--harden")
    if _ssh(host, cmd, json.dumps(st).encode()):
        raise SetuError("the install failed on the server; see the output above")
    _finish_deploy(args, st, first, tok, st["server"]["endpoint"])
    return 0


def cmd_destroy(args) -> int:
    cls = providers.PROVIDERS.get(args.provider)
    if not cls:
        raise SetuError("unknown provider")
    prov = providers.get(args.provider, args.token or os.environ.get(cls.token_env, ""))
    if not args.yes and input("Delete server %s on %s permanently? [y/N] " % (args.id, args.provider)).lower() != "y":
        print("Cancelled.")
        return 1
    prov.destroy(args.id)
    print("Deleted.")
    return 0


# --- parser -----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="setu", description="Set up your own WireGuard VPN in one command.")
    ap.add_argument("-V", "--version", action="version", version="setu " + __version__)
    ap.add_argument("-H", "--host", help="run the command on a remote server over SSH (user@host)")
    ap.add_argument("--state", help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    def add(name, help, **kw):
        return sub.add_parser(name, help=help, description=help, **kw)

    def common_vpn(p):
        p.add_argument("--first-device", default="phone", help="name of the first device (default: phone)")
        p.add_argument("--port", type=int, default=51820, help="WireGuard UDP port (default 51820)")
        p.add_argument("--dns", choices=DNS_CHOICES, default="adblock",
                       help="adblock = built-in filtering DNS on the server (default)")
        p.add_argument("--upstream", choices=list(config.DNS_PRESETS), default="cloudflare",
                       help="upstream DNS for adblock mode")
        p.add_argument("--blocklist", default="ads", help="ads | family | off | URL of a hosts-format list")
        p.add_argument("--mtu", type=int, default=None)

    p = add("deploy", "Create a VPN server: setu deploy " + "|".join(list(providers.PROVIDERS) + ["ssh"]))
    p.add_argument("target")
    common_vpn(p)
    p.add_argument("--token", help="provider API token (or use the provider's env var)")
    p.add_argument("--name", default="setu-vpn", help="server name")
    p.add_argument("--region", help="provider region/location")
    p.add_argument("--size", help="provider server size (default: smallest)")
    p.add_argument("--ssh-key", help="public key file to install for SSH access")
    p.add_argument("--host", dest="host", help="(ssh) user@server")
    p.add_argument("--harden", action="store_true", default=True)
    p.add_argument("--ref", default="main", help="Setu git ref the server downloads")
    p.add_argument("--out-dir", default="setu-output", help="where to save the first device config")
    p.set_defaults(fn=cmd_deploy)

    p = add("destroy", "Delete a cloud server created by `setu deploy`")
    p.add_argument("provider")
    p.add_argument("id")
    p.add_argument("--token")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(fn=cmd_destroy)

    srv = add("server", "Server-side install (run on the VPN host)").add_subparsers(dest="server_cmd", required=True)
    p = srv.add_parser("init", help="install and start the VPN on this machine")
    common_vpn(p)
    p.add_argument("--endpoint", help="public IP or domain clients connect to (default: auto-detect)")
    p.add_argument("--state-file", help="use a prepared state file ('-' for stdin)")
    p.add_argument("--ipv4-net", default="10.66.66.0/24")
    p.add_argument("--ipv6-net", default="fd66:66:66::/64")
    p.add_argument("--web-port", type=int, default=8080)
    p.add_argument("--no-web", action="store_true", help="do not run the web panel")
    p.add_argument("--allow-device-traffic", action="store_true", help="let devices reach each other")
    p.add_argument("--harden", action="store_true", help="enable ufw + automatic security updates")
    p.add_argument("--skip-packages", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_server_init)

    p = add("add", "Add a device and show its QR code")
    p.add_argument("name")
    p.add_argument("--expires", type=float, metavar="DAYS", help="auto-remove after N days (guests)")
    p.add_argument("--split", metavar="CIDRS", help="split tunnel: only route these networks, e.g. 10.0.0.0/8")
    p.add_argument("--public-key", help="bring your own key (the private key is then never stored)")
    p.add_argument("--out", help="save the .conf file")
    p.add_argument("--png", help="save the QR code as PNG")
    p.add_argument("--no-qr", action="store_true")
    p.add_argument("--show-config", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = add("remove", "Remove a device (its config stops working immediately)")
    p.add_argument("name")
    p.set_defaults(fn=cmd_remove)
    for nm, en, h in (("pause", False, "Temporarily disable a device"), ("resume", True, "Re-enable a paused device")):
        p = add(nm, h)
        p.add_argument("name")
        p.set_defaults(fn=lambda a, en=en: cmd_toggle(a, en))
    p = add("list", "List devices and who is connected")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = add("show", "Print a device's .conf")
    p.add_argument("name")
    p.add_argument("--out")
    p.set_defaults(fn=lambda a: cmd_show(a, False))
    p = add("qr", "Show a device's QR code again")
    p.add_argument("name")
    p.add_argument("--png")
    p.set_defaults(fn=lambda a: cmd_show(a, True))
    p = add("status", "Server summary")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)
    p = add("doctor", "Check that everything is healthy")
    p.set_defaults(fn=cmd_doctor)
    p = add("health", "Health checks plus uptime, load, memory and disk (exit 1 if anything fails)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_health)
    p = add("usage", "Data used per device (needs the 5-minute sampler, installed by default)")
    p.add_argument("name", nargs="?")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_usage)
    p = add("sample", "Record traffic counters (runs from a timer every 5 minutes)")
    p.set_defaults(fn=cmd_sample)
    p = add("card", "Write a one-page HTML setup card (QR + steps) to send to someone")
    p.add_argument("name")
    p.add_argument("--lang", choices=card.LANGS, default="en")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_card)
    p = add("expire", "Change when a device expires (days from now, or 'never')")
    p.add_argument("name")
    p.add_argument("days")
    p.set_defaults(fn=cmd_expire)
    p = add("web", "Run the web panel in the foreground")
    p.add_argument("--bind")
    p.add_argument("--port", type=int)
    p.set_defaults(fn=cmd_web)
    p = add("token", "Create a new web panel admin token")
    p.set_defaults(fn=cmd_token)

    p = add("dns", "Manage ad/tracker blocking")
    ds = p.add_subparsers(dest="dns_cmd", required=True)
    ds.add_parser("update", help="refresh the blocklist now")
    ds.add_parser("list", help="show your custom rules")
    for nm, h in (("block", "block a domain"), ("unblock", "remove your block"),
                  ("allow", "never block a domain"), ("disallow", "remove an allow rule")):
        q = ds.add_parser(nm, help=h)
        q.add_argument("domain")
    p.set_defaults(fn=cmd_dns)

    p = add("maintenance", "Daily job: expire devices, refresh blocklist (runs from a timer)")
    p.set_defaults(fn=cmd_maintenance)
    p = add("uninstall", "Remove Setu from this server")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--purge", action="store_true", help="also delete devices and keys")
    p.set_defaults(fn=cmd_uninstall)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.host and args.cmd not in ("deploy", "destroy"):
        # run the same command on the server: strip -H/--host and its value
        rest, skip = [], False
        for i, a in enumerate(argv):
            if skip:
                skip = False
            elif a in ("-H", "--host"):
                skip = True
            elif a.startswith("--host="):
                pass
            else:
                rest.append(a)
        return _ssh(args.host, ["sudo", "setu"] + rest, tty=True)
    try:
        return args.fn(args) or 0
    except SetuError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    except PermissionError:
        print("error: permission denied - run with sudo", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
