# Command reference

Run `setu COMMAND --help` for every option.

| Command | What it does |
|---|---|
| `setu deploy hetzner\|digitalocean\|vultr\|ssh` | Create a server (or set one up over SSH) and print the first QR code |
| `setu destroy PROVIDER ID` | Delete a cloud server made by `deploy` |
| `setu server init` | Install on the current machine (used by `install.sh`) |
| `setu add NAME` | Add a device. `--expires DAYS`, `--split CIDRS`, `--public-key KEY`, `--out FILE`, `--png FILE` |
| `setu remove NAME` | Remove a device |
| `setu pause NAME` / `setu resume NAME` | Disable or re-enable a device |
| `setu list [--json]` | Devices with state, last handshake and expiry |
| `setu show NAME` / `setu qr NAME` | Print the `.conf` or QR code again |
| `setu status` | Server summary and device list |
| `setu doctor` | Health checks with fix hints |
| `setu web` | Run the web panel in the foreground |
| `setu token` | New web panel admin token |
| `setu dns update\|list\|block D\|unblock D\|allow D\|disallow D` | Ad blocking rules |
| `setu maintenance` | Expire guests, refresh blocklist (run daily by a timer) |
| `setu uninstall [--purge]` | Remove Setu from this server |
| `setu -H user@server COMMAND` | Run any of the above on the server over SSH |

## Install options (`deploy` and `server init`)

| Option | Default | Meaning |
|---|---|---|
| `--first-device` | `phone` | Name of the first device |
| `--port` | `51820` | WireGuard UDP port |
| `--dns` | `adblock` | `adblock` (filtering DNS on the server) or `cloudflare`, `quad9`, `google`, `adguard`, `mullvad` |
| `--upstream` | `cloudflare` | Upstream resolver used by `adblock` |
| `--blocklist` | `ads` | `ads`, `family`, `off` or the URL of a hosts-format list |
| `--mtu` | auto | Lower it (for example 1380) on networks that drop large packets |
| `--allow-device-traffic` | off | Let devices reach each other |
| `--no-web` | off | Do not run the web panel |
