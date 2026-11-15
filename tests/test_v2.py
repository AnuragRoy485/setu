import datetime as dt
import json
import threading
import urllib.request

import pytest

from setu import card, cli, doctor, server, system, usage, web
from setu import state as S
from setu.providers import PROVIDERS


def T(*a):
    return dt.datetime(*a, tzinfo=dt.timezone.utc)


# --- usage history --------------------------------------------------------------------
def test_usage_counts_deltas_and_resets():
    data = {"version": 1, "last": {}, "devices": {}}
    usage.record(data, {"a": {"rx": 1000, "tx": 500}}, T(2026, 11, 15, 10, 0))
    assert data["devices"]["a"]["days"]["2026-11-15"] == [0, 0]  # first sight attributes nothing
    usage.record(data, {"a": {"rx": 4000, "tx": 900}}, T(2026, 11, 15, 10, 5))
    assert data["devices"]["a"]["days"]["2026-11-15"] == [3000, 400]
    # interface restarted: counters fell, so the new reading is all new traffic
    usage.record(data, {"a": {"rx": 200, "tx": 50}}, T(2026, 11, 15, 11, 0))
    assert data["devices"]["a"]["days"]["2026-11-15"] == [3200, 450]
    assert data["devices"]["a"]["hours"]["2026-11-15T11"] == [200, 50]


def test_usage_forgets_removed_devices_and_trims():
    data = {"version": 1, "last": {}, "devices": {}}
    usage.record(data, {"a": {"rx": 1, "tx": 1}, "b": {"rx": 1, "tx": 1}}, T(2026, 1, 1))
    usage.record(data, {"a": {"rx": 5, "tx": 5}}, T(2026, 1, 1, 1))
    assert "b" not in data["devices"] and "b" not in data["last"]
    usage.record(data, {"a": {"rx": 9, "tx": 9}}, T(2026, 6, 1))
    assert list(data["devices"]["a"]["days"]) == ["2026-06-01"]


def test_usage_series_fills_gaps():
    data = {"version": 1, "last": {}, "devices": {"a": {"hours": {}, "days": {"2026-11-14": [10, 20]}}}}
    sr = usage.series(data, "a", 3, T(2026, 11, 15, 12))
    assert [d["t"] for d in sr["days"]] == ["2026-11-13", "2026-11-14", "2026-11-15"]
    assert [d["rx"] for d in sr["days"]] == [0, 10, 0] and sr["total_tx"] == 20
    assert len(sr["hours"]) == 24
    assert usage.series(data, "nobody", 2)["total_rx"] == 0


def test_sample_reads_wg_dump(host, st, monkeypatch):
    pub = st["devices"]["alice-phone"]["public_key"]

    class R(system.Runner):
        n = 0

        def run(self, cmd, check=True, input=None):
            if cmd[:2] == ["wg", "show"]:
                R.n += 1000
                out = "priv\tpub\t51820\toff\n%s\tpsk\t1.2.3.4:5\t10.66.66.2/32\t100\t%d\t%d\t25\n" % (pub, R.n, R.n // 2)
                return type("P", (), {"returncode": 0, "stdout": out, "stderr": ""})()
            return super().run(cmd, check, input)

    r = R(True)
    usage.sample(st, r, T(2026, 11, 15, 9))
    usage.sample(st, r, T(2026, 11, 15, 9, 5))
    d = usage.load()
    assert d["devices"]["alice-phone"]["days"]["2026-11-15"] == [1000, 500]
    # bob is not connected: no history yet, but no crash
    assert "bob-laptop" not in d["devices"]


# --- health, cards, expiry, os detection ----------------------------------------------
def test_stats_and_summary(host, st):
    sy = system.stats()
    assert set(sy) == {"uptime_s", "load", "mem_used_pct", "disk_free_pct"}
    res = doctor.summary(st, system.Runner(True))
    assert isinstance(res["ok"], bool) and res["checks"] and "system" in res
    assert all({"name", "ok", "hint"} <= set(c) for c in res["checks"])


@pytest.mark.parametrize("lang", card.LANGS)
def test_card_renders_each_language(st, lang):
    html = card.render(st, st["devices"]["alice-phone"], lang)
    assert "<svg" in html and "alice-phone" in html and st["server"]["endpoint"] in html
    assert "script" not in html.lower()


def test_card_escapes_and_rejects_bad_lang(st):
    with pytest.raises(ValueError):
        card.render(st, st["devices"]["alice-phone"], "xx")


def test_set_expiry(st):
    when = S.set_expiry(st, "alice-phone", 2)
    assert when and not S.expired(st["devices"]["alice-phone"])
    assert S.set_expiry(st, "alice-phone", None) is None
    for bad in (-1, "abc", 99999):
        with pytest.raises(S.SetuError):
            S.set_expiry(st, "alice-phone", bad)
    with pytest.raises(S.SetuError):
        S.set_expiry(st, "ghost", 1)


def test_detect_os():
    assert server.detect_os("ID=ubuntu\nID_LIKE=debian\n") == "apt"
    assert server.detect_os('ID="fedora"\n') == "dnf"
    assert server.detect_os("ID=arch\n") == "pacman"
    assert server.detect_os("ID=endeavouros\nID_LIKE=arch\n") == "pacman"
    assert server.detect_os("ID=alpine\n") == "alpine"
    assert server.detect_os("ID=plan9\n") == "unknown"


def test_install_packages_arch_and_alpine(monkeypatch):
    monkeypatch.setattr(server, "detect_os", lambda text=None: "pacman")
    r = system.Runner(True)
    server.install_packages(r, adblock=True, harden=True)
    cmd = r.log[-1]
    assert cmd[0] == "pacman" and {"wireguard-tools", "dnsmasq", "ufw", "iptables"} <= set(cmd)
    monkeypatch.setattr(server, "detect_os", lambda text=None: "alpine")
    with pytest.raises(S.SetuError, match="OpenRC"):
        server.install_packages(system.Runner(True), True, False)


def test_init_installs_sampler_timer(host, st):
    r = system.Runner(True)
    server.write_units(st, r)
    unit_dir = host / "root/etc/systemd/system"
    assert (unit_dir / "setu-sample.timer").exists() and "OnUnitActiveSec=5min" in (unit_dir / "setu-sample.timer").read_text()
    assert ["systemctl", "enable", "--now", "setu-sample.timer"] in r.log


def run(host, *args):
    return cli.main(["--state", str(host / "state.json"), "--dry-run"] + list(args))


def test_cli_new_commands(host, st, capsys, tmp_path):
    S.Store(str(host / "state.json")).save(st)
    assert run(host, "expire", "alice-phone", "3") == 0
    assert "will expire" in capsys.readouterr().out
    assert run(host, "expire", "alice-phone", "never") == 0
    assert "will not expire" in capsys.readouterr().out
    out = tmp_path / "c.html"
    assert run(host, "card", "alice-phone", "--lang", "hi", "--out", str(out)) == 0
    assert "<svg" in out.read_text(encoding="utf-8") and oct(out.stat().st_mode & 0o777) == "0o600"
    assert run(host, "usage") == 0
    assert "alice-phone" in capsys.readouterr().out
    assert run(host, "usage", "--json", "--days", "3") == 0
    assert json.loads(capsys.readouterr().out)["devices"]["alice-phone"]["days"].__len__() == 3
    assert run(host, "usage", "ghost") == 1
    assert run(host, "sample") == 0
    run(host, "health", "--json")
    assert "checks" in json.loads(capsys.readouterr().out)


# --- web panel API --------------------------------------------------------------------
def test_web_new_endpoints(host):
    store = S.Store(str(host / "state.json"))
    s = S.new_state("198.51.100.4")
    S.add_device(s, "phone")
    token = S.set_web_token(s)
    store.save(s)
    srv = web.serve(store, system.Runner(True), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(path, method="GET", body=None, tok=token):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + tok})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    try:
        code, u = call("/api/usage")
        assert code == 200 and len(u["total_days"]) == 30 and "phone" in u["devices"]
        code, one = call("/api/devices/phone/usage")
        assert code == 200 and len(one["hours"]) == 24 and len(one["days"]) == 30
        assert call("/api/devices/ghost/usage")[0] == 400
        code, h = call("/api/health")
        assert code == 200 and "checks" in h and "system" in h
        code, e = call("/api/devices/phone/expiry", "POST", {"days": 7})
        assert code == 200 and e["expires"]
        assert store.load()["devices"]["phone"]["expires"] == e["expires"]
        assert call("/api/devices/phone/expiry", "POST", {"days": None})[1]["expires"] is None
        assert call("/api/devices/phone/expiry", "POST", {"days": "x"})[0] == 400
        for path in ("/api/usage", "/api/health", "/api/devices/phone/usage"):
            assert call(path, tok="wrong")[0] == 401
    finally:
        srv.shutdown()


# --- Scaleway -------------------------------------------------------------------------
def test_scaleway_create_and_destroy(monkeypatch):
    monkeypatch.setenv("SCW_DEFAULT_PROJECT_ID", "proj-1")
    calls = []

    class Resp:
        def __init__(self, d):
            self.d = json.dumps(d).encode()

        def read(self):
            return self.d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=None):
        body = req.data.decode() if req.data else None
        calls.append((req.get_method(), req.full_url, body, dict(req.headers)))
        url, m = req.full_url, req.get_method()
        if m == "POST" and url.endswith("/servers"):
            return Resp({"server": {"id": "abc"}})
        if m == "GET" and url.endswith("/servers/abc"):
            return Resp({"server": {"id": "abc", "public_ip": {"address": "51.0.0.9"}}})
        return Resp({})

    p = PROVIDERS["scaleway"]("secret", opener=opener)
    res = p.create("setu-vpn", "fr-par-1", "", "#!/bin/bash\necho hi\n")
    assert res == {"id": "fr-par-1/abc", "ip": "51.0.0.9"}
    create = json.loads(calls[0][2])
    assert create["commercial_type"] == "DEV1-S" and create["project"] == "proj-1" and create["image"] == "ubuntu_noble"
    assert calls[0][3]["X-auth-token"] == "secret" and "Authorization" not in calls[0][3]
    cloud = [c for c in calls if c[1].endswith("/user_data/cloud-init")][0]
    assert cloud[0] == "PATCH" and cloud[2] == "#!/bin/bash\necho hi\n" and cloud[3]["Content-type"] == "text/plain"
    assert json.loads([c for c in calls if c[1].endswith("/action")][0][2]) == {"action": "poweron"}
    p.destroy("fr-par-1/abc")
    assert calls[-1][1].endswith("/zones/fr-par-1/servers/abc/action") and json.loads(calls[-1][2]) == {"action": "terminate"}
    with pytest.raises(S.SetuError):
        p.destroy("abc")


def test_scaleway_needs_project(monkeypatch):
    monkeypatch.delenv("SCW_DEFAULT_PROJECT_ID", raising=False)
    p = PROVIDERS["scaleway"]("secret", opener=lambda *a, **k: None)
    with pytest.raises(S.SetuError, match="project"):
        p.create("n", "fr-par-1", "", "x")
