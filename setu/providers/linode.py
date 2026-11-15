from __future__ import annotations

import base64
import secrets
from typing import Any, Dict

from .base import Provider


class Linode(Provider):
    name = "linode"
    token_env = "LINODE_TOKEN"
    default_region = "us-east"
    api = "https://api.linode.com/v4"
    default_size = "g6-nanode-1"

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        # Linode takes public keys inline at create time, nothing to register.
        return public_key.strip()

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        body: Dict[str, Any] = {
            "region": region,
            "type": size or self.default_size,
            "image": "linode/ubuntu24.04",
            "label": name,
            # the API requires a root password with an image; it is never shown, SSH uses keys
            "root_pass": secrets.token_urlsafe(32) + "Aa1!",
            "metadata": {"user_data": base64.b64encode(user_data.encode()).decode()},
        }
        if ssh_key:
            body["authorized_keys"] = [ssh_key]
        inst = self.call("POST", "/linode/instances", body)

        def ip():
            i = self.call("GET", "/linode/instances/%s" % inst["id"])
            ips = i.get("ipv4") or []
            return ips[0] if ips else None

        return {"id": str(inst["id"]), "ip": self.wait_for(ip)}

    def destroy(self, server_id: str) -> None:
        self.call("DELETE", "/linode/instances/%s" % server_id)
