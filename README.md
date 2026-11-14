<table>
  <tr>
    <td><img src="app/static/logo.svg" alt="qbit-doctarr" width="80"></td>
    <td><h1>qbit-doctarr</h1></td>
  </tr>
</table>

**A lightweight maintenance suite for the *arr / qBittorrent ecosystem.**

qbit-doctarr sits alongside your existing Sonarr/Radarr/Lidarr/Readarr/Whisparr and qBittorrent stack as a **janitor** — it doesn't manage your active queue or replace your *arrs, it cleans up the things that fall through the cracks. Stalled torrents, orphaned metadata, dangerous files, unmonitored completed media, polite missing-media searches.

It's a single lightweight Docker container with a small web UI.

---

## Features

| Task | What it does |
|---|---|
| **Stalled Tracker** | Detects torrents stuck in metadata-fetch, slow-download, or 0 B/s seed state. Blocklists + re-searches in the *arr, or pauses completed seeds so the *arr can import. |
| **Unmonitor Downloaded** | Sweeps enabled *arrs and unmonitors media that has a file. Optional modes to also unmonitor complete seasons and ended series/deceased artists. |
| **Missing Media Search** | Politely searches for missing media in small batches with cooldowns — designed to avoid indexer bans. |
| **BT_Backup Repair** | Detects orphaned `.torrent` / `.fastresume` pairs in qBittorrent's metadata folder and quarantines the dangling half. |
| **Malicious File Scanner** | Blocks torrents containing `.exe`, `.scr`, `.js`, etc., while allowing torrents that contain both malicious and approved media files (skip the bad, keep the good). |
| **Unmanaged Torrents** | Deletes paused/stopped torrents older than a threshold that no *arr is tracking. |
| **Quarantine Cleanup** | Purges quarantined files older than the retention setting. |
| **Database Health** | Pings each enabled *arr's `/api/vX/health` and alerts on new warnings. |

Plus:

- **Dashboard** with per-task status cards and live countdowns
- **History page** with searchable, paginated task log
- **Trends page** with 24h / 7d / 30d charts of missing-media and stalled-torrent counts (30-day retention)
- **Notifications** (SMTP) with per-source muting and a periodic digest (daily / weekly / monthly)
- **Scheduler** with per-task intervals and per-task advisory timeouts
- **Global Dry Run** mode — everything simulates without deleting or modifying anything
- **Basic Auth** for the web UI

---

## Quick Start

**Prerequisites:** Docker + Docker Compose. The *arrs and qBittorrent already configured and working.

**1. Create a directory and a compose file:**

    mkdir qbit-doctarr && cd qbit-doctarr

Create `docker-compose.yml`:

    services:
      qbit-doctarr:
        image: ghcr.io/bdhamm/qbit-doctarr:latest
        container_name: qbit-doctarr
        restart: unless-stopped
        ports:
          - "5000:5000"
        environment:
          - PUID=1000
          - PGID=1000
          - PYTHONUNBUFFERED=1
          - TZ=UTC
        volumes:
          - ./config:/config
          - ./qbittorrent_data:/qbittorrent_data
          - ./downloads/quarantine:/downloads/quarantine

**2. Edit the file:**

- **`PUID`/`PGID`** — must match the user that owns your qBittorrent data directory. Check with `id` on the host. See the Requirements section below — this is the single most common cause of "the task found orphans but couldn't do anything about them" failures.
- **`TZ`** — your local timezone. Schedules and timestamps use it.
- **Volume paths** — point to your actual directories:
  - `/config` — will hold the SQLite DB and `config.json`. Relative `./config` works.
  - `/qbittorrent_data` — the **parent** of `BT_backup`. Typical Linux default: `~/.local/share/qBittorrent`. LinuxServer.io image: `/path/to/appdata/qbittorrent`.
  - `/downloads/quarantine` — must be read/write. Will hold files moved out of downloads by the BT_Backup Repair task.

**3. Start:**

    docker compose up -d

**4. Open the UI:** http://your-nas-ip:5000

**5. Configure in Settings:**

- qBittorrent URL + credentials
- Each *arr instance (URL + API key + **category**)
- Schedules for each task
- Thresholds (stalled timeouts, blocked extensions, etc.)

---

## First-time Configuration (read this — the category rule is mandatory)

### The category rule (critical)

**qbit-doctarr will only ever touch torrents whose category matches an enabled *arr's category.**

Every enabled *arr in qbit-doctarr's Settings has a `category` field (e.g., `servarr-sonarr`). Torrents in qBittorrent with any *other* category — including empty category — are **invisible** to every task:

- They are never scanned for dangerous files
- They are never evaluated as stalled
- They are never deleted as unmanaged

This is a deliberate safety mechanism. Manual downloads (games, ISOs, files fetched outside your *arrs) will never be affected by qbit-doctarr's cleanup tasks.

**If you're seeing "Found 0 torrents" or "Nothing to do" everywhere:** check that your *arr categories in qbit-doctarr's Settings match the categories qBittorrent actually assigns to downloaded torrents. Categories are **case-sensitive**.

### The "unmonitor" task requires opt-in per *arr

The Unmonitor Downloaded task is powerful — it flips the `monitored` flag in your *arrs. It's **disabled by default for each *arr**. Enable it per *arr in Settings under the *arr's row (`Unmonitor: Yes`).

### The Global Dry Run

Before turning the scheduler on for real, **enable Global Dry Run** in Settings. Everything will simulate: tasks run, find candidates, log what they *would* do — but nothing is deleted, nothing is changed. Review the History page and the per-task logs, confirm the actions look right, then disable Global Dry Run.

---

## How it works

- **Scheduler:** APScheduler runs each task on its own interval. Per-task timers can be set to `0` to disable the scheduled run without removing the task (you can still run it manually).
- **Database:** SQLite at `/config/qbit-doctarr.db`. Holds task history, missing-media tracking, stalled-torrent timers, and hourly metrics snapshots.
- **Config:** `config.json` at `/config/config.json`. Editable via the Settings UI; the file is JSON and can be hand-edited if needed (restart container after manual edits).
- **API access:** qbit-doctarr talks to qBittorrent's WebUI API and each *arr's `/api/vX/` REST API. It does **not** use any private or undocumented interfaces.
- **File access:** BT_Backup Repair reads qBittorrent's metadata folder. Quarantine Cleanup reads/writes `/downloads/quarantine`. No other filesystem access.

---

## Requirements

**PUID/PGID must match your host user.** qBittorrent, qbit-doctarr, and every *arr container must run as the same UID/GID.

Why: qbit-doctarr moves orphaned `.torrent` files out of qBittorrent's metadata folder. If it runs as a different user, it sees the files but cannot `unlink()` them, and every task reports "0 files" silently.

Check on your host:

    id
    # uid=1000(youruser) gid=1000(youruser) groups=1000(youruser),100(users)

Common values: `1000:1000` on most Linux. **Synology:** often `PGID=100` (the `users` group). **Unraid:** typically `99:100`.

---

## Known Limitations

- **`fail_torrent_in_arr` fallback-to-delete**: for an *arr-category torrent that is genuinely not found in any *arr queue (e.g., transient *arr error), qbit-doctarr will fall back to direct qBittorrent deletion with `deleteFiles=true`. The category guard prevents this for **non-*arr** categories, but *arr-category torrents remain vulnerable to a false-positive queue miss. This is a known watch item; a log-and-skip alternative is deferred.
- **Radarr indexer 429s** (rate limits) are external and cannot be fully mitigated. Blocklist actions are paced at 200ms to reduce the risk.
- **Basic Auth over plain HTTP** transmits credentials in cleartext. Only use it behind a reverse proxy that provides HTTPS.

---

## Disclaimer

**This tool deletes torrents and their downloaded files.** It also modifies `monitored` flags in your *arrs. Configure it carefully, use Global Dry Run first, and understand what each task does before enabling it.

The maintainer is not responsible for data loss caused by misconfiguration or by the known limitations above.

---

## Credits

qbit-doctarr stands on the shoulders of two fantastic open-source projects:

- **[Houndarr](https://github.com/elfhosted/houndarr)** — the inspiration for the polite missing-media search (batch sizing, cooldowns, per-item throttling). Houndarr's approach to indexer-safe searching is the model Missing Media Search follows.
- **[Maintainerr](https://github.com/jorenn92/Maintainerr)** — the inspiration for the unmonitor-downloaded-media concept. The idea of sweeping your library to unmonitor files that have successfully imported comes from Maintainerr's collection-management philosophy.

Thanks also to the **Sonarr / Radarr / Lidarr / Readarr / Whisparr** developers for the *arr ecosystem that makes tools like this useful.

---

## License

[MIT](LICENSE) © 2026 Bern Hammond
