#!/usr/bin/env bash
# Ship origin/master to the server and restart the bot.
# Usage: deploy/deploy.sh [user@host]   Default host: a `discordia` alias in ~/.ssh/config.
set -euo pipefail
HOST="${1:-${DISCORDIA_HOST:-discordia}}"

# The server pulls from GitHub, so a commit that isn't pushed would silently not ship.
git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]; then
    echo "HEAD isn't origin/master: push (or check out master) first." >&2
    exit 1
fi

# git runs as the service user: root trips git's "dubious ownership" guard on /opt/discordia.
# Stop, back up, start rather than restart: stopping (SIGINT) makes the old process save the world and
# post its digest, so the backup is that final save, taken before the new code migrates it.
ssh -- "$HOST" 'set -e
cd /opt/discordia
old=$(sudo -u discordia git rev-parse --short HEAD)
sudo -u discordia git pull --ff-only -q
new=$(sudo -u discordia git rev-parse --short HEAD)
echo "$old -> $new"

systemctl stop discordia
trap "systemctl start discordia" EXIT  # a failed backup or pip install must not leave the bot down
if [ -f discordia.db ]; then
    cp -p discordia.db "discordia.db.$(date +%Y%m%d-%H%M%S).$old.bak"
    ls -t discordia.db.*.bak | tail -n +6 | xargs -r rm --  # keep the last 5
fi
if ! sudo -u discordia git diff --quiet "$old" HEAD -- requirements.txt; then
    sudo -u discordia venv/bin/pip install -q -r requirements.txt
fi
systemctl start discordia

sleep 5
if ! systemctl is-active --quiet discordia; then
    journalctl -u discordia --since "-1min" --no-pager | tail -20
    echo "discordia did not come back up. To roll back:" >&2
    echo "  ssh discordia \"cd /opt/discordia && sudo -u discordia git reset --hard $old && systemctl restart discordia\"" >&2
    echo "  (the pre-deploy save is the newest discordia.db.*.$old.bak, if the save needs it too)" >&2
    exit 1
fi
echo active
journalctl -u discordia --since "-1min" --no-pager | grep -iE "started|connected|error|traceback" || true'
