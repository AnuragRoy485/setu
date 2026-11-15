"""Per-device data usage history.

A timer runs `setu sample` every few minutes. Each run reads the live WireGuard
byte counters and adds the difference since the last run into hourly buckets
(kept 3 days) and daily buckets (kept 90 days). Counters reset when the
interface restarts, which is handled: a lower reading counts as a fresh start.
Only byte counts and times are stored. No IPs, no domains, no endpoints.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

from . import system

HOURS_KEPT = 72
DAYS_KEPT = 90


def path() -> str:
    return os.path.join(system.ETC, "usage.json")


def load() -> Dict[str, Any]:
    try:
        with open(path()) as f:
            data = json.load(f)
        if isinstance(data, dict) and "devices" in data:
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "last": {}, "devices": {}}


def save(data: Dict[str, Any]) -> None:
    system.write(path(), json.dumps(data, sort_keys=True), 0o600)


def _hour_key(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H")


def _day_key(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d")


def record(data: Dict[str, Any], readings: Dict[str, Dict[str, int]], at: Optional[dt.datetime] = None) -> None:
    """Fold counter readings ({name: {"rx": n, "tx": n}}) into the history."""
    at = at or dt.datetime.now(dt.timezone.utc)
    hk, dk = _hour_key(at), _day_key(at)
    for name, cur in readings.items():
        last = data["last"].get(name)
        if last is None:
            d_rx, d_tx = 0, 0  # first sight: nothing to attribute yet
        else:
            d_rx = cur["rx"] - last["rx"] if cur["rx"] >= last["rx"] else cur["rx"]
            d_tx = cur["tx"] - last["tx"] if cur["tx"] >= last["tx"] else cur["tx"]
        data["last"][name] = {"rx": cur["rx"], "tx": cur["tx"]}
        dev = data["devices"].setdefault(name, {"hours": {}, "days": {}})
        for bucket, key in ((dev["hours"], hk), (dev["days"], dk)):
            old = bucket.get(key, [0, 0])
            bucket[key] = [old[0] + d_rx, old[1] + d_tx]
    # forget devices that no longer exist, and trim old buckets
    for name in list(data["devices"]):
        if name not in readings:
            data["devices"].pop(name, None)
            data["last"].pop(name, None)
    cut_h = _hour_key(at - dt.timedelta(hours=HOURS_KEPT))
    cut_d = _day_key(at - dt.timedelta(days=DAYS_KEPT))
    for dev in data["devices"].values():
        dev["hours"] = {k: v for k, v in dev["hours"].items() if k >= cut_h}
        dev["days"] = {k: v for k, v in dev["days"].items() if k >= cut_d}


def sample(st: Dict[str, Any], runner: system.Runner, at: Optional[dt.datetime] = None) -> Dict[str, Any]:
    peers = system.wg_dump(st, runner)
    readings = {}
    for name, dev in st["devices"].items():
        p = peers.get(dev["public_key"])
        if p:
            readings[name] = {"rx": p["rx"], "tx": p["tx"]}
    # devices not in the live interface (paused) keep their history but have no reading
    data = load()
    for name in st["devices"]:
        if name not in readings and name in data["last"]:
            readings[name] = data["last"][name]
    record(data, readings, at)
    save(data)
    return data


def series(data: Dict[str, Any], name: str, days: int = 30, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Daily and hourly series for charts: lists of {t, rx, tx}, oldest first, gaps filled with zero."""
    now = now or dt.datetime.now(dt.timezone.utc)
    dev = data["devices"].get(name, {"hours": {}, "days": {}})
    out_days: List[Dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        k = _day_key(now - dt.timedelta(days=i))
        rx, tx = dev["days"].get(k, [0, 0])
        out_days.append({"t": k, "rx": rx, "tx": tx})
    out_hours: List[Dict[str, Any]] = []
    for i in range(23, -1, -1):
        k = _hour_key(now - dt.timedelta(hours=i))
        rx, tx = dev["hours"].get(k, [0, 0])
        out_hours.append({"t": k, "rx": rx, "tx": tx})
    return {"name": name, "days": out_days, "hours": out_hours,
            "total_rx": sum(d["rx"] for d in out_days), "total_tx": sum(d["tx"] for d in out_days)}


def overview(data: Dict[str, Any], names: List[str], days: int = 30, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    per = {n: series(data, n, days, now) for n in names}
    total = []
    for i in range(days):
        rx = sum(per[n]["days"][i]["rx"] for n in names) if names else 0
        tx = sum(per[n]["days"][i]["tx"] for n in names) if names else 0
        t = per[names[0]]["days"][i]["t"] if names else ""
        total.append({"t": t, "rx": rx, "tx": tx})
    return {"devices": per, "total_days": total}
