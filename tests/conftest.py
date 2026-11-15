import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from setu import system
from setu import state as S


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A fake server root so nothing outside tmp_path is touched."""
    etc = tmp_path / "etc-setu"
    monkeypatch.setattr(system, "ETC", str(etc))
    monkeypatch.setattr(system, "ROOT", str(tmp_path / "root"))
    return tmp_path


@pytest.fixture
def st():
    s = S.new_state("203.0.113.7")
    S.add_device(s, "alice-phone")
    S.add_device(s, "bob-laptop")
    return s
