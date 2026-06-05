# paper-finder runbook

Operational guide for starting, checking, and restarting the running system.
For design, architecture, and decisions, see `PAPER_FINDER_MEMORY_BANK.md`.

## Components and dependency chain

Everything runs inside your logged-in macOS session, in this order of dependency:

1. You are logged in (LaunchAgents and Docker Desktop only run inside your session).
2. Docker Desktop is running (it hosts the Qdrant container).
3. The `paperfinder-qdrant` container is up on host port 6533 (REST) / 6534 (gRPC).
4. The launchd agent `com.bioratio.paperfinder.sync` runs `drive_sync.py` nightly at 02:30.

Files the system needs, all in the repo root
(`/Users/jchan/Projects/PaperFinder/paper-finder`):

- `.env` (config: embedder, vector store, HF offline, Drive folder names)
- `service_account.json` (Drive read credentials; never commit)
- `paperfinder.db` (the index)

Note on Qdrant status: the finder uses the SQLite / brute-force store today. It begins
using the `paperfinder-qdrant` container once the Qdrant store is wired in (Stage 2),
via `PAPERFINDER_VECTOR_STORE=qdrant` and a `paperfinder_chunks` collection on port 6533.
Until then the container can be up without the app depending on it.

## Quick status

    bash scripts/paperfinder-status.sh

Reports whether Docker, the Qdrant container, the Qdrant API, and the launchd agent
are healthy, plus the last few sync log lines.

## Cold start (after a reboot or OS update)

A reboot stops Docker and every container. After logging back in:

1. Start Docker Desktop (auto-starts if "Start Docker Desktop when you sign in" is on):

       open -a Docker

   Wait for the whale icon to settle, then confirm:

       docker info >/dev/null && echo "docker up"

2. Start the Qdrant container (auto-starts if its restart policy is set):

       docker start paperfinder-qdrant
       curl -fs http://localhost:6533/collections && echo "  qdrant ok"

3. The launchd agent is already loaded and runs at 02:30. To run a sync immediately:

       launchctl kickstart -k gui/$(id -u)/com.bioratio.paperfinder.sync
       tail -n 3 ~/Library/Logs/paperfinder-sync.log

With Docker set to start at login and the container restart policy in place, steps 1
and 2 happen on their own after login; the status script confirms it.

## Restart and stop

Restart just Qdrant:

    docker restart paperfinder-qdrant

Reload the agent (after editing the plist):

    launchctl bootout gui/$(id -u)/com.bioratio.paperfinder.sync
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bioratio.paperfinder.sync.plist

Stop the system and leave it down:

    docker stop paperfinder-qdrant
    launchctl bootout gui/$(id -u)/com.bioratio.paperfinder.sync

## The nightly job

- Schedule: 02:30 daily. If the Mac is asleep then, it runs at the next wake.
- Action: in-place Drive backfill (new files embedded, removed files archived).
- Log: `~/Library/Logs/paperfinder-sync.log`, one line per run or an error reason.
- Run on demand: the `kickstart` command above.
- Real embedder: `.env` sets `PAPERFINDER_EMBEDDER=st`; `HF_HUB_OFFLINE=1` keeps model
  loads offline once the model is cached.

## Troubleshooting

- `docker ps` errors with "Cannot connect to the Docker daemon": Docker Desktop is not
  running. Run `open -a Docker` and wait for it to start.
- Container not listed by `docker ps`: it is stopped. Run `docker start paperfinder-qdrant`.
  If `docker ps -a` does not list it at all, recreate it:

       docker run -d --name paperfinder-qdrant --restart unless-stopped \
         -p 6533:6333 -p 6534:6334 \
         -v paperfinder_qdrant_storage:/qdrant/storage qdrant/qdrant:latest

- Sync log shows `AUTH FAILED`: `service_account.json` is missing or unreadable in the
  repo root.
- Sync log shows folders "not visible to the service account": share the Drive folder
  with the service account email (Viewer).
- Agent missing from `launchctl list`: re-bootstrap it (see Restart and stop).
- Logged out overnight: nothing runs. Docker, Qdrant, and the agent all need your
  session, so stay logged in for the nightly job to fire.
