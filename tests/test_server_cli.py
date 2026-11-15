import json
import os
import subprocess
import threading
import urllib.request

import pytest

from setu import cli, cloudinit, config, doctor, server, system, web
from setu import state as S
from setu.providers import PROVIDERS


def run_cli(host, *args):
    return cli.main(["--state", str(host / "state.json"), "--dry-run"] + list(args))


def test_server_init_writes_everything(host, st):
    store = S.Store(str(host / "state.json"))
    runner = system.Runner(dry_run=True)
    fake_list = "0.0.0.0 ads.example.com\n0.0.0.0 track.example.net\n"
    server.init(st, store, runner, harden_host=True, fetch=lambda u: fake_list, log=lambda *a: None)
    etc = host / "etc-setu"
    assert (host / "root/etc/wireguard/wg0.conf").read_text().count("[Peer]") == 2
    assert oct((host / "root/etc/wireguard/wg0.conf").stat().st_mode & 0o777) == "0o600"
    assert (etc / "postup.sh").stat().st_mode & 0o111
    assert "listen-address=10.66.66.1" in (etc / "dnsmasq.conf").read_text()
    assert (etc / "blocklist.hosts").read_text().count("0.0.0.0") == 2
    assert (host / "root/etc/sysctl.d/99-setu.conf").read_text().startswith("net.ipv4.ip_forward=1")
    units = host / "root/etc/systemd/system"
    for u in ("setu-dns.service", "setu-web.service", "setu-maintenance.timer"):
        assert (units / u).exists()
    assert "--bind 10.66.66.1" in (units / "setu-web.service").read_text()
    assert (host / "root/usr/local/bin/setu").exists()
    cmds = [" ".join(c) for c in runner.log]
    assert any("apt-get install" in c and "wireguard" in c and "dnsmasq-base" in c for c in cmds)
    assert any(c.startswith("systemctl enable --now wg-quick@wg0") for c in cmds)
    assert any(c == "ufw allow 51820/udp" for c in cmds)
    assert store.load()["server"]["endpoint"] == "203.0.113.7"


@pytest.mark.parametrize("os_release,expected", [
    ('NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n', "apt"),
    ('NAME="Debian GNU/Linux"\nID=debian\n', "apt"),
    ('ID=raspbian\nID_LIKE=debian\n', "apt"),
    ('NAME="Fedora Linux"\nID=fedora\n', "dnf"),
    ('NAME="Rocky Linux"\nID="rocky"\nID_LIKE="rhel centos fedora"\n', "dnf"),
    ('ID=almalinux\n', "dnf"),
    ('NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.20.3\n', "apk"),
    ('NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n', "pacman"),
    ('NAME="EndeavourOS"\nID="endeavouros"\nID_LIKE="arch"\n', "pacman"),
    ('ID=archarm\nID_LIKE=arch\n', "pacman"),
    ('NAME="Gentoo"\nID=gentoo\nPRETTY_NAME="Gentoo Linux aarch64"\n', "unknown"),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "unknown"),
])
def test_detect_os(host, os_release, expected):
    (host / "root/etc/os-release").write_text(os_release)
    assert server.detect_os() == expected


def test_detect_os_fallback_and_missing(host):
    (host / "root/etc/os-release").unlink()
    assert server.detect_os() == "unknown"
    usr_lib = host / "root/usr/lib"
    usr_lib.mkdir(parents=True)
    (usr_lib / "os-release").write_text("ID=arch\n")
    assert server.detect_os() == "pacman"


def test_install_packages_distros(host):
    rel = host / "root/etc/os-release"

    rel.write_text("ID=alpine\n")
    r = system.Runner(dry_run=True)
    server.install_packages(r, adblock=True, harden=True)
    assert r.log == [
        ["apk", "add", "--no-cache", "wireguard-tools", "iptables", "ip6tables",
         "iproute2", "ca-certificates", "dnsmasq"],
        ["apk", "add", "--no-cache", "ufw"],
    ]
    r = system.Runner(dry_run=True)
    server.install_packages(r, adblock=False, harden=False)
    assert r.log == [["apk", "add", "--no-cache", "wireguard-tools", "iptables", "ip6tables",
                      "iproute2", "ca-certificates"]]

    rel.write_text("ID=arch\n")
    r = system.Runner(dry_run=True)
    server.install_packages(r, adblock=True, harden=True)
    assert r.log == [["pacman", "-Sy", "--noconfirm", "--needed",
                      "wireguard-tools", "iptables", "iproute2", "ca-certificates", "dnsmasq", "ufw"]]
    r = system.Runner(dry_run=True)
    server.install_packages(r, adblock=False, harden=False)
    assert r.log == [["pacman", "-Sy", "--noconfirm", "--needed",
                      "wireguard-tools", "iptables", "iproute2", "ca-certificates"]]

    rel.write_text("ID=fedora\n")
    r = system.Runner(dry_run=True)
    server.install_packages(r, adblock=True, harden=False)
    assert r.log == [["dnf", "install", "-y", "wireguard-tools", "iptables", "iproute", "dnsmasq"]]

    rel.write_text("ID=gentoo\n")
    with pytest.raises(S.SetuError, match="Alpine and Arch Linux.*dnsmasq.*--skip-packages"):
        server.install_packages(system.Runner(dry_run=True), adblock=True, harden=False)
    with pytest.raises(S.SetuError) as exc:
        server.install_packages(system.Runner(dry_run=True), adblock=False, harden=False)
    assert "dnsmasq" not in str(exc.value) and "--skip-packages" in str(exc.value)


def test_server_init_arch_linux(host, st):
    (host / "root/etc/os-release").write_text('NAME="Arch Linux"\nID=arch\n')
    store = S.Store(str(host / "state.json"))
    runner = system.Runner(dry_run=True)
    server.init(st, store, runner, harden_host=True, fetch=lambda u: "0.0.0.0 ads.example.com\n", log=lambda *a: None)
    cmds = [" ".join(c) for c in runner.log]
    assert any(c.startswith("pacman -Sy --noconfirm --needed wireguard-tools") and "dnsmasq" in c and "ufw" in c for c in cmds)
    assert any(c == "systemctl enable --now wg-quick@wg0" for c in cmds)
    assert any(c == "ufw allow 51820/udp" for c in cmds)
    assert (host / "root/etc/systemd/system/setu-dns.service").exists()
    assert not (host / "root/etc/apt/apt.conf.d/20auto-upgrades").exists()


def test_server_init_and_uninstall_alpine(host, st):
    (host / "root/etc/os-release").write_text('NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.20.0\n')
    store = S.Store(str(host / "state.json"))
    runner = system.Runner(dry_run=True)
    server.init(st, store, runner, harden_host=True, fetch=lambda u: "0.0.0.0 ads.example.com\n", log=lambda *a: None)
    cmds = [" ".join(c) for c in runner.log]
    assert any(c.startswith("apk add --no-cache wireguard-tools") and "dnsmasq" in c for c in cmds)
    assert any(c == "apk add --no-cache ufw" for c in cmds)
    assert any(c == "rc-service setu-wg restart" for c in cmds)
    assert any(c == "rc-service setu-dns restart" for c in cmds)
    assert any(c == "rc-service setu-web restart" for c in cmds)
    assert not any(c.startswith("systemctl") for c in cmds)

    init_dir = host / "root/etc/init.d"
    for svc in ("setu-wg", "setu-dns", "setu-web"):
        p = init_dir / svc
        assert p.exists() and (p.stat().st_mode & 0o111)
        res = subprocess.run(["sh", "-n"], input=p.read_text(), text=True, capture_output=True)
        assert res.returncode == 0, res.stderr
    cron = host / "root/etc/periodic/daily/setu-maintenance"
    assert cron.exists() and (cron.stat().st_mode & 0o111)
    assert subprocess.run(["sh", "-n"], input=cron.read_text(), text=True, capture_output=True).returncode == 0

    checks = doctor.run_checks(st, system.Runner(dry_run=True))
    assert any(name == "DNS filter (setu-dns) running" and ok for name, ok, _ in checks)

    class DownRunner(system.Runner):
        def run(self, cmd, check=True, input=None):
            self.log.append(cmd)
            rc = 1 if cmd[:3] == ["ip", "link", "show"] else 0
            return subprocess.CompletedProcess(cmd, rc, "", "")

    dr = DownRunner(dry_run=True)
    system.reload_wireguard(st, dr)
    assert ["rc-service", "setu-wg", "restart"] in dr.log
    system.restart_dns(st, dr)
    assert ["rc-service", "setu-dns", "restart"] in dr.log

    un_runner = system.Runner(dry_run=True)
    server.uninstall(st, un_runner, purge=True)
    un_cmds = [" ".join(c) for c in un_runner.log]
    assert any(c == "rc-service setu-wg stop" for c in un_cmds)
    assert not any(c.startswith("systemctl") for c in un_cmds)
    assert not (init_dir / "setu-wg").exists() and not cron.exists()


def test_cli_add_remove_pause_list(host, st, capsys):
    store = S.Store(str(host / "state.json"))
    store.save(S.new_state("198.51.100.4"))
    assert run_cli(host, "add", "alice-phone", "--out", str(host / "a.conf"), "--png", str(host / "a.png")) == 0
    out = capsys.readouterr().out
    assert "Added alice-phone (10.66.66.2)" in out and "Scan with the WireGuard app" in out
    assert "Endpoint = 198.51.100.4:51820" in (host / "a.conf").read_text()
    assert (host / "a.png").read_bytes()[:4] == b"\x89PNG"
    assert run_cli(host, "add", "alice-phone") == 1
    assert "already exists" in capsys.readouterr().err
    assert run_cli(host, "pause", "alice-phone") == 0
    assert "alice-phone" not in (host / "root/etc/wireguard/wg0.conf").read_text().replace("# alice-phone", "") or \
        "[Peer]" not in (host / "root/etc/wireguard/wg0.conf").read_text()
    assert run_cli(host, "resume", "alice-phone") == 0
    assert run_cli(host, "list") == 0
    assert "alice-phone" in capsys.readouterr().out
    assert run_cli(host, "show", "alice-phone") == 0
    assert "[Interface]" in capsys.readouterr().out
    assert run_cli(host, "remove", "alice-phone") == 0
    assert S.Store(str(host / "state.json")).load()["devices"] == {}
    assert run_cli(host, "remove", "alice-phone") == 1


def test_cli_dns_rules(host, capsys):
    store = S.Store(str(host / "state.json"))
    store.save(S.new_state("198.51.100.4"))
    assert run_cli(host, "dns", "block", "Evil.Example.com") == 0
    assert "address=/evil.example.com/0.0.0.0" in (host / "etc-setu/custom-dns.conf").read_text()
    assert run_cli(host, "dns", "unblock", "evil.example.com") == 0
    assert "evil.example.com" not in (host / "etc-setu/custom-dns.conf").read_text()


def test_maintenance_expires(host):
    store = S.Store(str(host / "state.json"))
    s = S.new_state("198.51.100.4")
    d = S.add_device(s, "guest", expires_days=1)
    d["expires"] = "2000-01-01T00:00:00Z"
    S.add_device(s, "keep")
    store.save(s)
    gone = server.maintenance(store, system.Runner(True), fetch=lambda u: "0.0.0.0 a.example\n")
    assert gone == ["guest"] and list(store.load()["devices"]) == ["keep"]


def test_uninstall_keeps_or_purges(host, st):
    store = S.Store(str(host / "state.json"))
    server.init(st, store, system.Runner(True), fetch=lambda u: "0.0.0.0 a.example\n", log=lambda *a: None)
    server.uninstall(st, system.Runner(True))
    assert not (host / "root/etc/wireguard/wg0.conf").exists() and (host / "etc-setu").exists()
    server.uninstall(st, system.Runner(True), purge=True)
    assert not (host / "etc-setu").exists()


def test_web_api_end_to_end(host):
    store = S.Store(str(host / "state.json"))
    s = S.new_state("198.51.100.4")
    token = S.set_web_token(s)
    store.save(s)
    srv = web.serve(store, system.Runner(True), "127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port

    def call(path, method="GET", body=None, tok=token):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": "Bearer " + tok} if tok else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    try:
        assert call("/")[0] == 200 and "Setu" in call("/")[1]
        assert call("/api/devices", tok="wrong")[0] == 401
        assert call("/api/devices", tok="")[0] == 401
        assert call("/api/devices", "POST", {"name": "phone"})[0] == 201
        assert call("/api/devices", "POST", {"name": "phone"})[0] == 400
        assert call("/api/devices", "POST", {"name": "../x"})[0] == 400
        code, body = call("/api/devices")
        assert code == 200 and json.loads(body)["devices"][0]["name"] == "phone"
        code, conf = call("/api/devices/phone/config")
        assert code == 200 and "[Interface]" in conf and "Endpoint = 198.51.100.4:51820" in conf
        code, svg = call("/api/devices/phone/qr.svg")
        assert code == 200 and svg.startswith("<svg")
        assert json.loads(call("/api/devices/phone/toggle", "POST")[1])["enabled"] is False
        assert call("/api/devices/phone", "DELETE")[0] == 200
        assert call("/api/devices/phone/config")[0] == 400
        assert call("/nope")[0] == 404
    finally:
        srv.shutdown()


class FakeResp:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_api(routes, calls):
    def opener(req, timeout=None):
        key = (req.get_method(), req.full_url)
        calls.append((key, json.loads(req.data) if req.data else None, dict(req.headers)))
        for (m, suffix), resp in routes.items():
            if m == req.get_method() and req.full_url.endswith(suffix):
                return FakeResp(resp)
        raise AssertionError("unexpected call %s" % (key,))
    return opener


def test_hetzner_create():
    calls = []
    routes = {
        ("GET", "/server_types?per_page=50"): {"server_types": [
            {"name": "big", "architecture": "x86", "cpu_type": "shared", "prices": [{"location": "hel1", "price_monthly": {"gross": "9.0"}}]},
            {"name": "small", "architecture": "x86", "cpu_type": "shared", "prices": [{"location": "hel1", "price_monthly": {"gross": "3.5"}}]},
            {"name": "arm", "architecture": "arm", "cpu_type": "shared", "prices": [{"location": "hel1", "price_monthly": {"gross": "1.0"}}]},
            {"name": "ded", "architecture": "x86", "cpu_type": "dedicated", "prices": [{"location": "hel1", "price_monthly": {"gross": "0.5"}}]}]},
        ("POST", "/servers"): {"server": {"id": 42, "public_net": {"ipv4": {"ip": "5.6.7.8"}}}},
    }
    p = PROVIDERS["hetzner"]("tok", opener=fake_api(routes, calls))
    res = p.create("setu-vpn", "hel1", "", "#!/bin/bash\n")
    assert res == {"id": "42", "ip": "5.6.7.8"}
    post = [c for c in calls if c[0][0] == "POST"][0]
    assert post[1]["server_type"] == "small" and post[1]["location"] == "hel1" and post[1]["image"] == "ubuntu-24.04"
    assert post[2]["Authorization"] == "Bearer tok"


def test_digitalocean_create(monkeypatch):
    calls = []
    routes = {("POST", "/droplets"): {"droplet": {"id": 7}},
              ("GET", "/droplets/7"): {"droplet": {"networks": {"v4": [{"type": "private", "ip_address": "10.0.0.2"}, {"type": "public", "ip_address": "9.9.9.9"}]}}}}
    p = PROVIDERS["digitalocean"]("tok", opener=fake_api(routes, calls))
    assert p.create("n", "blr1", "", "ud") == {"id": "7", "ip": "9.9.9.9"}
    assert calls[0][1]["region"] == "blr1" and calls[0][1]["size"] == "s-1vcpu-512mb-10gb"


def test_vultr_create():
    calls = []
    routes = {("GET", "/os?per_page=500"): {"os": [{"id": 1, "name": "Debian 12 x64"}, {"id": 2284, "name": "Ubuntu 24.04 LTS x64"}]},
              ("POST", "/instances"): {"instance": {"id": "abc"}},
              ("GET", "/instances/abc"): {"instance": {"main_ip": "4.3.2.1"}}}
    p = PROVIDERS["vultr"]("tok", opener=fake_api(routes, calls))
    assert p.create("n", "blr", "", "hello") == {"id": "abc", "ip": "4.3.2.1"}
    body = [c for c in calls if c[0][0] == "POST"][0][1]
    assert body["os_id"] == 2284 and body["user_data"] == "aGVsbG8="


def test_linode_create():
    calls = []
    routes = {
        ("POST", "/linode/instances"): {"id": 99, "ipv4": []},
        ("GET", "/linode/instances/99"): {"id": 99, "ipv4": ["1.2.3.4"]},
    }
    p = PROVIDERS["linode"]("tok", opener=fake_api(routes, calls))
    key = p.ensure_ssh_key("setu", "ssh-ed25519 AAAA test")
    assert p.create("n", "us-east", "", "hello", key) == {"id": "99", "ip": "1.2.3.4"}
    body = [c for c in calls if c[0][0] == "POST"][0][1]
    assert body["image"] == "linode/ubuntu24.04" and body["type"] == "g6-nanode-1"
    assert body["metadata"]["user_data"] == "aGVsbG8="
    assert len(body["root_pass"]) >= 32 and body["authorized_keys"] == ["ssh-ed25519 AAAA test"]


def test_provider_needs_token():
    with pytest.raises(S.SetuError):
        PROVIDERS["hetzner"]("")


def test_cloudinit_is_valid_bash(st):
    script = cloudinit.build(st, ref="main", harden=True, ssh_key_given=True)
    res = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
    assert res.returncode == 0, res.stderr
    assert "setu server init --state-file /etc/setu/bootstrap.json --harden" in script
    assert "rm -f /etc/setu/bootstrap.json" in script and "PasswordAuthentication no" in script
    with pytest.raises(ValueError):
        cloudinit.build(st, ref="main; rm -rf /")


def test_cloudinit_payload_roundtrip(st):
    import base64
    import re
    script = cloudinit.build(st)
    b = re.search(r"echo '([A-Za-z0-9+/=]+)' \| base64 -d", script).group(1)
    assert json.loads(base64.b64decode(b))["server"]["public_key"] == st["server"]["public_key"]


def test_deploy_flow_with_fake_provider(host, monkeypatch, capsys):
    import setu.providers as P

    class Fake:
        default_region = "x"
        token_env = "T"
        created = {}

        def __init__(self, token, **kw):
            pass

        def create(self, name, region, size, ud, key=None):
            Fake.created["ud"] = ud
            return {"id": "99", "ip": "192.0.2.55"}

    monkeypatch.setitem(P.PROVIDERS, "fake", Fake)
    monkeypatch.setattr(cli, "DEPLOY_FILE", str(host / "deployments.json"))
    out = host / "out"
    assert cli.main(["deploy", "fake", "--token", "t", "--out-dir", str(out), "--first-device", "me"]) == 0
    conf = (out / "me.conf").read_text()
    assert "Endpoint = 192.0.2.55:51820" in conf
    assert oct((out / "admin-token.txt").stat().st_mode & 0o777) == "0o600"
    assert json.loads((host / "deployments.json").read_text())[0]["ip"] == "192.0.2.55"
    # the client conf's server key must match what the server will install
    import base64, re
    b = re.search(r"echo '([A-Za-z0-9+/=]+)' \| base64 -d", Fake.created["ud"]).group(1)
    srv = json.loads(base64.b64decode(b))
    assert srv["server"]["public_key"] in conf
    assert list(srv["devices"]) == ["me"] and srv["devices"]["me"]["public_key"]
    assert "Setu is" not in capsys.readouterr().err
