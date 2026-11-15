# Providers

`setu deploy <provider>` talks to the provider's HTTPS API with the Python standard library and boots a fresh **Ubuntu 24.04** server with a cloud-init script.

| Provider | Token | Where to get it |
|---|---|---|
| `hetzner` | `HCLOUD_TOKEN` | Cloud Console > project > Security > API tokens (read and write) |
| `digitalocean` | `DIGITALOCEAN_TOKEN` | Control Panel > API > Generate New Token (write scope) |
| `vultr` | `VULTR_API_KEY` | Account > API > Enable API (and allow your IP) |
| `linode` | `LINODE_TOKEN` | Cloud Manager > Profile > API Tokens (read/write for Linodes) |

Pass the token with `--token` instead of the variable if you prefer. Tokens are never written to disk.

Options: `--name`, `--region`, `--size`, `--ssh-key ~/.ssh/id_ed25519.pub`, `--first-device`, `--dns`, `--port`, `--out-dir`.

If you pass `--ssh-key`, the key is registered with the provider, installed on the server and password SSH login is turned off.

## Oracle Cloud, AWS, GCP and others

Create an Ubuntu VM with a public IP yourself, open **UDP 51820** in its firewall or security group, then:

```sh
setu deploy ssh --host ubuntu@203.0.113.10
```

Oracle Cloud's "Always Free" VMs work well for this.

## Add a provider

1. Copy `setu/providers/vultr.py`.
2. Set `name`, `token_env`, `default_region`, `api`.
3. Implement `create(name, region, size, user_data, ssh_key)` returning `{"id", "ip"}` and `destroy(id)`.
4. Register it in `setu/providers/__init__.py`.
5. Add a test with a fake API (see `tests/test_server_cli.py`).
