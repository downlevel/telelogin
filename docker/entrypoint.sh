#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    # Any entry not owned by 10001 (old root-owned volume, files left by a root exec session)
    if [ -n "$(find /app/data \( \! -user 10001 -o \! -group 10001 \) -print -quit)" ]; then
        chown -R 10001:10001 /app/data
    fi
    exec setpriv --reuid=10001 --regid=10001 --init-groups -- "$@"
fi

exec "$@"
