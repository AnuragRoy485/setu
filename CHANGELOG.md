# Changelog

## 0.2.0

- Web panel rebuilt: server health card, 30-day traffic chart, per-device 24 hour and 30 day usage, search, copy config, expiry editing, auto-refresh, light and dark theme
- Per-device data usage history (`setu usage`, `setu sample`, 5-minute timer). Only byte counts are stored
- `setu health [--json]` with uptime, load, memory and disk; `setu doctor` now checks IPv6 and disk space
- `setu card NAME --lang en|hi|bn`: one-page setup card with QR code and plain steps; `setu deploy` writes one too
- `setu expire NAME DAYS|never`
- New providers: Linode (thanks @HarshRajSinghania, PR #6), Scaleway (not yet run against a live account)
- Arch Linux, Manjaro and EndeavourOS servers; Alpine gets a clear error instead of a crash
- Docs in Hindi and Bengali (`docs/clients.hi.md`, `docs/clients.bn.md`)
- QR test no longer flaky: decoded with zxing-cpp, which reads every code Setu makes. OpenCV misreads about 1 in 7 large valid codes

## 0.1.0 - first release

- `setu deploy` for Hetzner, DigitalOcean, Vultr and any SSH server
- WireGuard server with per-device keys and pre-shared keys, IPv4 + IPv6
- QR codes in the terminal, PNG and the web panel (built-in encoder)
- Ad and tracker blocking DNS with allow and block rules
- Web panel bound to the VPN address
- Guest devices that expire, split tunnel, bring-your-own-key devices
- `setu doctor`, `setu uninstall`, daily maintenance timer
