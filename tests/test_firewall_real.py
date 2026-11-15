"""Runs the generated firewall script against real iptables in a throwaway network
namespace (needs `unshare -rn`; skipped where that is not available)."""
import shutil
import subprocess

import pytest

from setu import config
from setu import state as S

pytestmark = pytest.mark.skipif(not shutil.which("unshare") or not shutil.which("iptables"),
                                reason="needs unshare + iptables")


def sh(script):
    return subprocess.run(["unshare", "-rn", "sh", "-c", script], capture_output=True, text=True)


@pytest.fixture
def scripts(tmp_path):
    st = S.new_state("1.2.3.4")
    up, down = tmp_path / "up.sh", tmp_path / "down.sh"
    up.write_text(config.render_firewall(st, True))
    down.write_text(config.render_firewall(st, False))
    return str(up), str(down)


SETUP = ("ip link set lo up; ip link add wg0 type dummy; ip link add eth9 type dummy; "
         "ip addr add 192.0.2.2/24 dev eth9; ip link set eth9 up; ip route add default via 192.0.2.1 dev eth9; ")


def test_up_is_idempotent_and_down_cleans(scripts):
    if sh("true").returncode != 0 or sh(SETUP).returncode != 0:
        pytest.skip("cannot create a network namespace here")
    up, down = scripts
    res = sh(SETUP + "sh %s; sh %s; iptables -t nat -S POSTROUTING; iptables -S FORWARD; echo ---; sh %s; "
             "iptables -t nat -S POSTROUTING; iptables -S FORWARD" % (up, up, down))
    first, second = res.stdout.split("---")
    assert first.count("-A POSTROUTING") == 1  # running twice does not duplicate
    assert first.count("-A FORWARD -i wg0 -j ACCEPT") == 1
    assert "-A FORWARD -i wg0 -o wg0 -j DROP" in first
    assert "-A" not in second  # everything removed again
