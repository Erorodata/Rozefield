#!/bin/sh
# Rozefield Server on Linux (mini PC, Raspberry Pi, VPS). Runs in this terminal; for start-on-boot use install_linux.sh.
#   ./start_server.sh                       start
#   ./start_server.sh --set-admin-password X   password for the control panel on your PC, then exit
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c "import google.protobuf, cramjam" 2>/dev/null || "$PY" -m pip install --user -q "protobuf>=4.25" "cramjam>=2.8" \
  || "$PY" -m pip install --break-system-packages -q "protobuf>=4.25" "cramjam>=2.8"
GAME=${GAME:-../Overfield}
[ -f game_path.txt ] && GAME=$(cat game_path.txt)
RES=""
[ -d "$GAME/launcher_Data/yoo" ] && RES="--res-dir $GAME/launcher_Data/yoo"
exec "$PY" rozefield_server.py $RES "$@"
