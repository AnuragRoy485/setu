# Security

Setu sets up a VPN, so security reports matter. Please do not open a public issue for a vulnerability.
Use GitHub's private "Report a vulnerability" button on the Security tab of this repository.

Design notes that are good to know:

- Device private keys are stored in `/etc/setu/state.json` (root only, mode 600). Use `setu add NAME --public-key KEY` to keep a device key off the server.
- The web panel listens on the VPN address only and is protected by a bearer token.
- Cloud deploys pass the server key through the provider's user-data and delete the on-disk copy after install.
