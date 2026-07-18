#!/bin/bash
# Baut die eingebettete Windows-Server-Runtime für die Desktop-App:
#   runtime/python/  Embeddable CPython (win_amd64) + alle Abhängigkeiten
#   runtime/app/     das ai_systems-Python-Paket
# Wird von electron-builder als extraResources mit in den Installer gepackt;
# main.js startet daraus beim App-Start automatisch den Server.
# Aufruf (Linux/macOS/WSL, braucht: curl, unzip, pip):  bash build_runtime.sh
set -euo pipefail
cd "$(dirname "$0")"

PYV=3.11.9
PYSHORT=311
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== 1/4: Embeddable Python $PYV (win_amd64) laden"
rm -rf runtime
mkdir -p runtime/python "runtime/app/ai_systems"
curl -fsSL -o "$WORK/pyembed.zip" \
  "https://www.python.org/ftp/python/$PYV/python-$PYV-embed-amd64.zip"
unzip -q "$WORK/pyembed.zip" -d runtime/python

echo "== 2/4: Abhängigkeiten als win_amd64-Wheels laden und entpacken"
mkdir -p runtime/python/Lib/site-packages
pip download --quiet --dest "$WORK/wheels" \
  --platform win_amd64 --python-version "$PYSHORT" --only-binary=:all: \
  -r ../requirements.txt
for whl in "$WORK"/wheels/*.whl; do
  unzip -qo "$whl" -d runtime/python/Lib/site-packages
done

echo "== 3/4: sys.path der Embeddable-Distribution um site-packages erweitern"
printf 'python%s.zip\n.\nLib/site-packages\n' "$PYSHORT" > "runtime/python/python$PYSHORT._pth"

echo "== 4/4: ai_systems-Paket einbetten"
cp ../*.py ../demo_data.json runtime/app/ai_systems/

echo "Fertig: $(du -sh runtime | cut -f1) unter electron/runtime/"
