# Contributing to Setu

Thanks for helping. Setu is small on purpose: Python standard library only, no build step.

## Run it locally

```sh
git clone https://github.com/AnuragRoy485/setu && cd setu
python3 -m pytest          # pip install pytest (zxing-cpp, numpy and cryptography are optional extra checks: QR codes are decoded with zxing-cpp)
python3 -m setu --help
```

Tests never touch your system: they use a temporary directory and a dry-run command runner.

## Good first issues

- Add a provider (UpCloud, AWS Lightsail, Oracle). Copy `setu/providers/vultr.py`, implement `create` and `destroy`, add a fake-API test like the others in `tests/test_server_cli.py`, and list it in `setu/providers/__init__.py` and the README table.
- Translate `docs/clients.md` into another language (Hindi and Bengali exist) and add the language to `setu/card.py`.
- Add Alpine support (needs OpenRC service files) in `setu/server.py`.
- Run Setu on a real server and report what broke. This is the most valuable contribution right now.

## Pull requests

- Keep dependencies at zero. If you need one, open an issue first.
- Add or update a test. Run `python3 -m pytest` before you push.
- Keep the README images in sync: `python3 scripts/build_assets.py` (needs Google Chrome).
- Write commit messages in plain English.

By contributing you agree that your work is released under the MIT license.

## CI

CI runs on every push and pull request (`.github/workflows/ci.yml`, Python 3.10 and 3.12).
