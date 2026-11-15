from __future__ import annotations

import base64
from typing import Any, Dict

from ..state import SetuError
from .base import Provider


class Vultr(Provider):
    name = "vultr"
    token_env = "VULTR_API_KEY"
    default_region = "blr"
    api = "https://api.vultr.com/v2"
    default_size = "vc2-1c-1gb"

    def _ubuntu_id(self) -> int:
        for o in self.call("GET", "/os?per_page=500")["os"]:
            if o["name"].lower().startswith("ubuntu 24.04") and "x64" in o["name"].lower():
                return o["id"]
        raise SetuError("could not find Ubuntu 24.04 in Vultr's OS list")

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        for k in self.call("GET", "/ssh-keys?per_page=100")["ssh_keys"]:
            if k["ssh_key"].split()[:2] == public_key.split()[:2]:
                return k["id"]
        return self.call("POST", "/ssh-keys", {"name": name, "ssh_key": public_key})["ssh_key"]["id"]

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        body: Dict[str, Any] = {"region": region, "plan": size or self.default_size, "os_id": self._ubuntu_id(),
                                "label": name, "hostname": name, "enable_ipv6": True,
                                "user_data": base64.b64encode(user_data.encode()).decode()}
        if ssh_key:
            body["sshkey_id"] = [ssh_key]
        inst = self.call("POST", "/instances", body)["instance"]

        def ip():
            i = self.call("GET", "/instances/%s" % inst["id"])["instance"]
            ip = i.get("main_ip")
            return ip if ip and ip != "0.0.0.0" else None
        return {"id": inst["id"], "ip": self.wait_for(ip)}

    def destroy(self, server_id: str) -> None:
        self.call("DELETE", "/instances/%s" % server_id)
