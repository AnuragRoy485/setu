# Connecting your devices

Install the official WireGuard app, then import the config Setu gives you.

| Device | App | Import |
|---|---|---|
| iPhone / iPad | WireGuard (App Store) | **+ > Create from QR code**, scan the QR from `setu add` |
| Android | WireGuard (Play Store, F-Droid) | **+ > Scan from QR code** |
| macOS | WireGuard (Mac App Store) | **Import tunnel(s) from file** (`setu show NAME --out NAME.conf`) |
| Windows | wireguard.com/install | **Import tunnel(s) from file** |
| Linux | `sudo apt install wireguard` | `sudo cp NAME.conf /etc/wireguard/ && sudo wg-quick up NAME` |

Tips

- One config per device. Do not share one config between two devices; they would kick each other off.
- To check it works, open <https://ifconfig.me> and confirm it shows your server's IP.
- On iOS and Android turn on **On-demand** (iOS) or **Always-on VPN** (Android) so the tunnel restarts by itself.
- Lost phone? `setu remove NAME` and its config stops working immediately.
