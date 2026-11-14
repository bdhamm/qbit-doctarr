#!/bin/bash
set -e

# If the first argument is a flag, prepend python run.py
if [ "${1:0:1}" = '-' ]; then
    set -- python run.py "$@"
fi

# If running as root, map the user and drop privileges
if [ "$(id -u)" = '0' ]; then
    PUID=${PUID:-1000}
    PGID=${PGID:-1000}

    # Create group if it doesn't exist (Using -o to allow non-unique GID)
    if ! getent group abc >/dev/null; then
        groupadd -o -g "$PGID" abc
    else
        groupmod -o -g "$PGID" abc
    fi

    # Create user if it doesn't exist (Using -o to allow non-unique UID)
    if ! getent passwd abc >/dev/null; then
        useradd -o -u "$PUID" -g abc -d /config -s /bin/bash abc
    else
        usermod -o -u "$PUID" -g abc abc
    fi

    # Defensive: create container-side directories before chowning.
    # No-op when volumes are mounted; prevents crash-loops if a bind mount
    # was omitted or the image is run without compose.
    mkdir -p /config /downloads/quarantine /downloads/torrent_files /qbittorrent_data

    # Ensure /config and /downloads/quarantine are owned by the user
    echo "Ensuring ownership of /config and /downloads/quarantine..."
    chown -R abc:abc /config
    chown -R abc:abc /downloads/quarantine

    echo "Switching to user abc (UID: $PUID, GID: $PGID)"
    exec gosu abc "$@"
fi

exec "$@"