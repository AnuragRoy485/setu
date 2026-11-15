from __future__ import annotations

import base64
from typing import Any, Dict

from ..state import SetuError
from .base import Provider


class Linode(Provider):
    name = "linode"
    token_env = "LINODE_TOKEN"
    default_region = "us-east"
    api = "https://api.linode.com/v4"
    default_size = "g6-nanode-1"

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        for k in self.call("GET", "/profile/sshkeys")["data"]:
            if k["ssh_key"].split()[:2] == public_key.split()[:2]:
                return k["id"]
        return self.call("POST", "/profile/sshkeys", {"label": name, "ssh_key": public_key})["id"]

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        body: Dict[str, Any] = {
            "region": region,
            "type": size or self.default_size,
            "image": "linode/ubuntu24.04",
            "label": name,
            "user_data": base64.b64encode(user_data.encode()).decode(),
        }
        if ssh_key:
            body["ssh_keys"] = [ssh_key]
        inst = self.call("POST", "/linode/instances", body)

        def ip():
            i = self.call("GET", "/linode/instances/%s" % inst["id"])
            ips = i.get("ipv4") or []
            return ips[0] if ips else None

        return {"id": str(inst["id"]), "ip": self.wait_for(ip)}

    def destroy(self, server_id: str) -> None:
        self.call("DELETE", "/linode/instances/%s" % server_id)
