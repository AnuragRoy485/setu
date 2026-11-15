from __future__ import annotations

from typing import Any, Dict

from .base import Provider


class DigitalOcean(Provider):
    name = "digitalocean"
    token_env = "DIGITALOCEAN_TOKEN"
    default_region = "blr1"
    api = "https://api.digitalocean.com/v2"
    default_size = "s-1vcpu-512mb-10gb"

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        for k in self.call("GET", "/account/keys?per_page=200")["ssh_keys"]:
            if k["public_key"].split()[:2] == public_key.split()[:2]:
                return k["id"]
        return self.call("POST", "/account/keys", {"name": name, "public_key": public_key})["ssh_key"]["id"]

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        body: Dict[str, Any] = {"name": name, "region": region, "size": size or self.default_size,
                                "image": "ubuntu-24-04-x64", "user_data": user_data, "ipv6": True}
        if ssh_key:
            body["ssh_keys"] = [ssh_key]
        did = self.call("POST", "/droplets", body)["droplet"]["id"]

        def ip():
            d = self.call("GET", "/droplets/%s" % did)["droplet"]
            for n in d.get("networks", {}).get("v4", []):
                if n.get("type") == "public":
                    return n["ip_address"]
            return None
        return {"id": str(did), "ip": self.wait_for(ip)}

    def destroy(self, server_id: str) -> None:
        self.call("DELETE", "/droplets/%s" % server_id)
