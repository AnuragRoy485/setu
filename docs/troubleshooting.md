# Troubleshooting

Start with `sudo setu doctor` on the server. It prints what is wrong and how to fix it.

| Problem | Likely cause and fix |
|---|---|
| Connects but no handshake | UDP 51820 is blocked. Open it in the cloud firewall or security group (Oracle, AWS, GCP block it by default). |
| Handshake works, no internet | Forwarding or NAT is missing. `setu doctor`, then `sudo systemctl restart wg-quick@wg0`. |
| Websites load slowly or hang | MTU too high. Redeploy with `--mtu 1380` or edit the device's `MTU` line. |
| A site breaks with ad blocking on | `setu dns allow thatsite.com` |
| Panel does not open | You must be connected to the VPN. Use `http://10.66.66.1:8080`, not the server's public IP. |
| Forgot the panel token | `sudo setu token` |
| Cloud deploy finished but nothing answers | The server needs 2-3 minutes. Install log: `/var/log/setu-install.log` on the server. |
