from __future__ import annotations

from typing import Any, Dict

from ..state import SetuError
from .base import Provider


class Hetzner(Provider):
    name = "hetzner"
    token_env = "HCLOUD_TOKEN"
    default_region = "hel1"
    api = "https://api.hetzner.cloud/v1"

    def cheapest_type(self, region: str) -> str:
        """Smallest x86 shared-CPU type offered in the location (prices and names change)."""
        types = self.call("GET", "/server_types?per_page=50")["server_types"]
        best = None
        for t in types:
            if t.get("architecture") != "x86" or t.get("deprecated") or t.get("cpu_type") != "shared":
                continue
            price = None
            for pr in t.get("prices", []):
                if pr.get("location") == region:
                    price = float(pr["price_monthly"]["gross"])
            if price is None:
                continue
            if best is None or price < best[0]:
                best = (price, t["name"])
        if not best:
            raise SetuError("no suitable Hetzner server type in %s; pass --size" % region)
        return best[1]

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        keys = self.call("GET", "/ssh_keys?per_page=50")["ssh_keys"]
        for k in keys:
            if k["public_key"].split()[:2] == public_key.split()[:2]:
                return k["id"]
        return self.call("POST", "/ssh_keys", {"name": name, "public_key": public_key})["ssh_key"]["id"]

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        body: Dict[str, Any] = {"name": name, "server_type": size or self.cheapest_type(region),
                                "image": "ubuntu-24.04", "location": region, "user_data": user_data,
                                "start_after_create": True,
                                "public_net": {"enable_ipv4": True, "enable_ipv6": True}}
        if ssh_key:
            body["ssh_keys"] = [ssh_key]
        res = self.call("POST", "/servers", body)["server"]
        ip = res["public_net"]["ipv4"]["ip"]
        return {"id": str(res["id"]), "ip": ip}

    def destroy(self, server_id: str) -> None:
        self.call("DELETE", "/servers/%s" % server_id)
