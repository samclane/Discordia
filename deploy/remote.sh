#!/usr/bin/env bash
# The server half of deploy.sh: pull, back up the save, restart. Lives on the server, root-owned and outside the
# repo, as /usr/local/sbin/discordia-deploy, and the CI deploy key may run nothing else (a forced command in root's
# authorized_keys). So pushing to master changes what the bot runs, never what root runs. After editing this:
#   ssh discordia 'install -m 755 /dev/stdin /usr/local/sbin/discordia-deploy' < deploy/remote.sh
set -euo pipefail
cd /opt/discordia
# git runs as the service user: root trips git's "dubious ownership" guard on /opt/discordia.
old=$(sudo -u discordia git rev-parse --short HEAD)
sudo -u discordia git pull --ff-only -q
new=$(sudo -u discordia git rev-parse --short HEAD)
echo "$old -> $new"

# Stop, back up, start rather than restart: stopping (SIGINT) makes the old process save the world and post its
# digest, so the backup is that final save, taken before the new code migrates it.
systemctl stop discordia
trap "systemctl start discordia" EXIT # a failed backup or pip install must not leave the bot down
# Backups go where the bot can't write: root prunes them by name, and the bot names what's in its own folder.
db=/var/lib/discordia/discordia.db
backups=/var/backups/discordia
if [ -f "$db" ]; then
    install -d -m 700 "$backups"
    cp "$db" "$backups/discordia.db.$(date +%Y%m%d-%H%M%S).$old.bak"
    ls -t "$backups"/discordia.db.*.bak | tail -n +6 | xargs -r rm -- # keep the last 5
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
    echo "  (the pre-deploy save is the newest $backups/discordia.db.*.$old.bak, if the save needs it too)" >&2
    exit 1
fi
echo active
journalctl -u discordia --since "-1min" --no-pager | grep -iE "started|connected|error|traceback" || true
