#!/bin/sh
# Setu server installer. Run on a fresh Ubuntu/Debian/Fedora/Alpine/Arch VPS as root:
#   curl -fsSL https://raw.githubusercontent.com/AnuragRoy485/setu/main/install.sh | sudo sh
# Extra arguments go to `setu server init`, e.g.  | sudo sh -s -- --dns quad9 --first-device laptop
set -eu

REF="${SETU_REF:-main}"
REPO="AnuragRoy485/setu"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sudo sh" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Installing python3 ..."
  if command -v apt-get >/dev/null 2>&1; then apt-get update -y && apt-get install -y python3
  elif command -v dnf >/dev/null 2>&1; then dnf install -y python3
  elif command -v apk >/dev/null 2>&1; then apk add --no-cache python3
  elif command -v pacman >/dev/null 2>&1; then pacman -Sy --noconfirm --needed python
  else echo "Please install python3 and run this again." >&2; exit 1; fi
fi

if ! command -v curl >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then apt-get install -y curl ca-certificates
  elif command -v dnf >/dev/null 2>&1; then dnf install -y curl
  elif command -v apk >/dev/null 2>&1; then apk add --no-cache curl ca-certificates
  elif command -v pacman >/dev/null 2>&1; then pacman -Sy --noconfirm --needed curl ca-certificates; fi
fi

mkdir -p /opt/setu
echo "Downloading Setu ($REF) ..."
curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" | tar xz -C /opt/setu --strip-components=1

cd /opt/setu
exec env PYTHONPATH=/opt/setu python3 -m setu server init "$@"
