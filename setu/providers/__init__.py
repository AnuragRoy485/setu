"""Cloud providers. Each one needs only an API token and the standard library."""
from __future__ import annotations

from .base import Provider
from .digitalocean import DigitalOcean
from .hetzner import Hetzner
from .vultr import Vultr

PROVIDERS = {"hetzner": Hetzner, "digitalocean": DigitalOcean, "vultr": Vultr}


def get(name: str, token: str, **kw) -> Provider:
    from ..state import SetuError
    try:
        return PROVIDERS[name](token, **kw)
    except KeyError:
        raise SetuError("unknown provider %r (choose: %s, or use `setu deploy ssh`)" % (name, ", ".join(PROVIDERS)))
