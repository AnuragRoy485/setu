import ipaddress
import subprocess

import pytest

from setu import config, state as S


def test_addresses_unique_and_sequential(st):
    assert st["devices"]["alice-phone"]["ipv4"] == "10.66.66.2"
    assert st["devices"]["bob-laptop"]["ipv4"] == "10.66.66.3"
    assert st["devices"]["alice-phone"]["ipv6"] == "fd66:66:66::2"
    assert st["devices"]["alice-phone"]["user"] == "alice"


def test_reuses_freed_addresses(st):
    S.remove_device(st, "alice-phone")
    assert S.add_device(st, "carol")["ipv4"] == "10.66.66.2"


@pytest.mark.parametrize("bad", ["", "Has Space", "-x", "a" * 40, "../etc"])
def test_bad_names(st, bad):
    with pytest.raises(S.SetuError):
        S.add_device(st, bad)


def test_duplicate_and_missing(st):
    with pytest.raises(S.SetuError):
        S.add_device(st, "alice-phone")
    with pytest.raises(S.SetuError):
        S.remove_device(st, "ghost")


def test_pool_exhaustion():
    s = S.new_state("1.2.3.4", ipv4_net="10.9.9.0/30")
    S.add_device(s, "a")
    with pytest.raises(S.SetuError):
        S.add_device(s, "b")


def test_bring_your_own_key(st):
    pub = "mLv7T0tH0qV0v9m0F4yqkQ3o6bT8x8y8o8d8t8m8l8k="
    d = S.add_device(st, "byok", public_key=pub)
    assert d["private_key"] is None and d["public_key"] == pub
    assert "<PASTE YOUR PRIVATE KEY HERE>" in config.render_client_conf(st, d)
    with pytest.raises(S.SetuError):
        S.add_device(st, "bad", public_key="short")


def test_expiry_prune(st):
    S.add_device(st, "guest", expires_days=1)
    assert S.prune(st) == []
    import datetime as dt
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
    assert S.prune(st, later) == ["guest"]
    assert "guest" not in st["devices"]


def test_server_conf(st):
    text = config.render_server_conf(st)
    assert text.count("[Peer]") == 2
    assert "ListenPort = 51820" in text and "Address = 10.66.66.1/24, fd66:66:66::1/64" in text
    assert st["devices"]["alice-phone"]["public_key"] in text
    st["devices"]["bob-laptop"]["enabled"] = False
    assert config.render_server_conf(st).count("[Peer]") == 1


def test_client_conf(st):
    d = st["devices"]["alice-phone"]
    text = config.render_client_conf(st, d)
    assert "Address = 10.66.66.2/32, fd66:66:66::2/128" in text
    assert "DNS = 10.66.66.1, fd66:66:66::1" in text  # adblock mode uses the server
    assert "Endpoint = 203.0.113.7:51820" in text and "AllowedIPs = 0.0.0.0/0, ::/0" in text
    assert "PersistentKeepalive = 25" in text and st["server"]["public_key"] in text
    d["allowed_ips"] = "10.0.0.0/8"
    assert "AllowedIPs = 10.0.0.0/8" in config.render_client_conf(st, d)
    st["server"]["endpoint"] = "2001:db8::1"
    assert "Endpoint = [2001:db8::1]:51820" in config.render_client_conf(st, d)


def test_dns_modes():
    s = S.new_state("1.1.1.1", dns="quad9")
    assert config.client_dns(s)[0] == "9.9.9.9" and not config.uses_local_dns(s)


def test_firewall_script_is_valid_shell(st):
    for up in (True, False):
        script = config.render_firewall(st, up)
        res = subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True)
        assert res.returncode == 0, res.stderr
    up = config.render_firewall(st, True)
    assert "MASQUERADE" in up and "10.66.66.0/24" in up and "fd66:66:66::/64" in up
    assert "-i wg0 -o wg0 -j DROP" in up  # devices isolated by default
    st["server"]["isolate_clients"] = False
    assert "-o wg0 -j DROP" not in config.render_firewall(st, True)


def test_dnsmasq_and_blocklist(st):
    text = config.render_dnsmasq(st, "/h", "/c")
    assert "listen-address=10.66.66.1,fd66:66:66::1" in text and "server=1.1.1.1" in text
    hosts = "127.0.0.1 localhost\n0.0.0.0 ads.example.com tracker.example.net # c\n0.0.0.0 good.example.org\n"
    out = config.parse_hosts(hosts, allow=["good.example.org"])
    assert "0.0.0.0 ads.example.com" in out and "localhost" not in out and "good.example.org" not in out


def test_web_token(st):
    t = S.set_web_token(st)
    assert S.check_web_token(st, t) and not S.check_web_token(st, "wrong") and not S.check_web_token(st, "")


def test_network_valid(st):
    ipaddress.ip_network(st["server"]["ipv4_net"])
