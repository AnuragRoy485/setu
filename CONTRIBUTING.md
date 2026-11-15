# Contributing to Setu

Thanks for helping. Setu is small on purpose: Python standard library only, no build step.

## Run it locally

```sh
git clone https://github.com/AnuragRoy485/setu && cd setu
python3 -m pytest          # pip install pytest (opencv-python-headless and cryptography are optional extra checks)
python3 -m setu --help
```

Tests never touch your system: they use a temporary directory and a dry-run command runner.

## Good first issues

- Add a provider (Linode, Scaleway, UpCloud, AWS Lightsail). Copy `setu/providers/vultr.py`, implement `create` and `destroy`, add a fake-API test like the others in `tests/test_server_cli.py`, and list it in `setu/providers/__init__.py` and the README table.
- Translate `docs/clients.md`.
- Add Alpine or Arch support in `setu/server.py` (`install_packages`).
- Show per-device data usage history in the web panel.

## Pull requests

- Keep dependencies at zero. If you need one, open an issue first.
- Add or update a test. Run `python3 -m pytest` before you push.
- Keep the README images in sync: `python3 scripts/build_assets.py` (needs Google Chrome).
- Write commit messages in plain English.

By contributing you agree that your work is released under the MIT license.

## CI

`docs/ci-workflow.yml.example` is a ready GitHub Actions workflow. Copy it to `.github/workflows/ci.yml` to run the tests on every push.
