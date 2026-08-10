#!/usr/bin/env bash
set -euo pipefail

echo "============================================"
echo " Gamepad MIDI Studio - macOS 构建"
echo "============================================"

python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

python3 -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name GamepadMIDIStudio \
  --icon "assets/icon.icns" \
  --add-data "gms/ui:gms/ui" \
  run.py

echo
echo "构建完成：dist/GamepadMIDIStudio/GamepadMIDIStudio"
