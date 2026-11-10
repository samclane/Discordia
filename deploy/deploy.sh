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

# The rest happens on the server, in deploy/remote.sh as installed there (see its header).
ssh -- "$HOST" /usr/local/sbin/discordia-deploy
