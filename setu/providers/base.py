from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..state import SetuError


class Provider:
    name = "base"
    token_env = ""
    default_region = ""
    api = ""

    def __init__(self, token: str, opener=None):
        if not token:
            raise SetuError("no API token for %s (set %s or pass --token)" % (self.name, self.token_env))
        self.token = token
        self._open = opener or urllib.request.urlopen

    def headers(self) -> Dict[str, str]:
        """Auth headers; a provider with a different scheme overrides this."""
        return {"Authorization": "Bearer " + self.token}

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
             raw: Optional[str] = None) -> Dict[str, Any]:
        """JSON request; pass `raw` instead of `body` to send plain text."""
        if raw is not None:
            data, ctype = raw.encode(), "text/plain"
        else:
            data, ctype = (json.dumps(body).encode() if body is not None else None), "application/json"
        hdrs = {"Content-Type": ctype, "User-Agent": "setu"}
        hdrs.update(self.headers())
        req = urllib.request.Request(self.api + path, data=data, method=method, headers=hdrs)
        try:
            with self._open(req, timeout=60) as r:
                raw = r.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            raise SetuError("%s API error %s on %s %s: %s" % (self.name, e.code, method, path, detail))
        except urllib.error.URLError as e:
            raise SetuError("cannot reach %s API: %s" % (self.name, e.reason))
        return json.loads(raw) if raw else {}

    def wait_for(self, fn, timeout: int = 300, every: float = 4.0):
        end = time.time() + timeout
        while time.time() < end:
            val = fn()
            if val:
                return val
            time.sleep(every)
        raise SetuError("timed out waiting for %s to give the server an IP" % self.name)

    # interface -------------------------------------------------------------
    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        raise NotImplementedError

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        """Create the server; returns {"id": ..., "ip": ...} once it has a public IPv4."""
        raise NotImplementedError

    def destroy(self, server_id: str) -> None:
        raise NotImplementedError
