from __future__ import annotations

import os
from typing import Any, Dict

from ..state import SetuError
from .base import Provider


class Scaleway(Provider):
    """Scaleway Instances (Paris, Amsterdam, Warsaw).

    Needs an API secret key (SCW_SECRET_KEY) and your project id (SCW_DEFAULT_PROJECT_ID).
    Server ids look like "fr-par-1/<uuid>" because deleting needs the zone.
    """
    name = "scaleway"
    token_env = "SCW_SECRET_KEY"
    default_region = "fr-par-1"
    api = "https://api.scaleway.com"
    default_size = "DEV1-S"

    def headers(self) -> Dict[str, str]:
        return {"X-Auth-Token": self.token}

    def _project(self) -> str:
        proj = os.environ.get("SCW_DEFAULT_PROJECT_ID", "")
        if not proj:
            raise SetuError("Scaleway needs your project id: set SCW_DEFAULT_PROJECT_ID "
                            "(Console > Project settings)")
        return proj

    def ensure_ssh_key(self, name: str, public_key: str) -> Any:
        proj = self._project()
        keys = self.call("GET", "/iam/v1alpha1/ssh-keys?project_id=%s&page_size=100" % proj).get("ssh_keys", [])
        for k in keys:
            if k["public_key"].split()[:2] == public_key.split()[:2]:
                return k["id"]
        return self.call("POST", "/iam/v1alpha1/ssh-keys",
                         {"name": name, "public_key": public_key, "project_id": proj})["id"]

    def create(self, name: str, region: str, size: str, user_data: str, ssh_key: Any = None) -> Dict[str, str]:
        zone = region or self.default_region
        base = "/instance/v1/zones/%s/servers" % zone
        body = {"name": name, "commercial_type": size or self.default_size, "image": "ubuntu_noble",
                "project": self._project(), "dynamic_ip_required": True, "enable_ipv6": True}
        srv = self.call("POST", base, body)["server"]
        sid = srv["id"]
        self.call("PATCH", "%s/%s/user_data/cloud-init" % (base, sid), raw=user_data)
        self.call("POST", "%s/%s/action" % (base, sid), {"action": "poweron"})

        def ip():
            s = self.call("GET", "%s/%s" % (base, sid))["server"]
            pub = s.get("public_ip") or (s.get("public_ips") or [None])[0]
            return (pub or {}).get("address") or None

        return {"id": "%s/%s" % (zone, sid), "ip": self.wait_for(ip)}

    def destroy(self, server_id: str) -> None:
        zone, _, sid = server_id.partition("/")
        if not sid:
            raise SetuError("Scaleway ids look like zone/uuid, for example fr-par-1/0a1b... (got %r)" % server_id)
        self.call("POST", "/instance/v1/zones/%s/servers/%s/action" % (zone, sid), {"action": "terminate"})
