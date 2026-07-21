# Setting up a new lecture-capture PC — full runbook

Hand this file to a fresh Claude Code session (or a human) with no other
context, running **on the classroom PC itself**. Following it end-to-end
takes a brand-new Windows PC to a fully working, wiki-managed capture agent
that records audio + PTZ camera and streams both into the existing
Harbour.Wiki → Knottra pipeline.

This assumes the **backend already exists** (Railway project `harbour-wiki`
with services `harbour-wiki`, `knottra`, `Postgres`) — you are onboarding one
more classroom PC into it, not building the backend from scratch. If the
backend itself needs to be created, stop and read `CLAUDE.md` +
`PIPELINE.md` at the repo root first; this doc only covers the capture side.

Read this whole file before touching anything — the "Known issues" section
at the bottom describes failure modes you *will* hit, and the fixes are not
obvious from the error messages alone.

## 0. What you're setting up

```
mic ──▶ faster-whisper (local) ──▶ POST /api/ingest ──▶ Harbour.Wiki ──▶ Knottra ─▶ fused notes
PTZ cam ──▶ board/desk crop ──▶ POST /api/vision   ──▶ Harbour.Wiki ──▶ Knottra ─┘
                                                              │
                                                              ▼
                                          /api/capture/{heartbeat,schedule,control}
                                          (agent reports status, pulls its timetable,
                                           operator dashboard at /capture)
```

The classroom PC never holds the Knottra key or the LLM key — only a
`CAPTURE_TOKEN` shared with Harbour.Wiki. Harbour.Wiki is the single gateway.

## 1. Prerequisites

- Windows PC, physically in the classroom, with the PTZ camera (e.g.
  Logitech PTZ Pro 2) and a microphone connected.
- **Local admin rights on this account, if at all possible.** A locked-down
  standard account will still get audio + camera recording working, but
  several pieces (Task Scheduler auto-start, fully freeing a stuck camera,
  OBS's virtual-camera driver) silently degrade without admin — see Known
  Issues #1, #4, #5. Budget extra time and expect manual workarounds if you
  don't have it.
- Git, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/) installed.
  `uv` install: `pip install uv` or `winget install --id astral-sh.uv`.
- [Railway CLI](https://docs.railway.com/reference/cli-api): install with
  `npm install -g @railway/cli`. **On Windows, always invoke it via
  PowerShell, not Git Bash** — Git Bash on these classroom PCs is frequently
  a minimal build with no coreutils and a Windows-style `PATH`, so the
  installed `railway` shim can't resolve `node`/`sed`/etc. Call the absolute
  path if `railway` isn't on PowerShell's `PATH` either:
  `& "$env:APPDATA\npm\railway.cmd" <command>`.
- Someone with access to the Railway project (`harbour-wiki`) who can either
  run `railway login` themselves or hand you the values below.

## 2. One-time backend check (skip if already confirmed working)

Link the CLI and confirm the harbour-wiki service already has what it needs.
**Never print/commit the actual secret values — only check that the keys
exist.**

```powershell
railway login                      # opens a browser OAuth flow
railway link -p harbour-wiki       # pick the "production" environment when prompted
railway variables --service harbour-wiki --kv
```

Confirm these keys are present (values are already set correctly if this
backend has been used before — don't regenerate them casually, other
classroom PCs and the operator dashboard depend on the same values):

| Variable | Purpose |
|---|---|
| `APP_DATABASE_URL` | Postgres for the wiki's own tables (courses, capture agents/schedules — separate schema from Knottra) |
| `CAPTURE_TOKEN` | Shared secret between every capture PC and the wiki. Same value goes in every PC's `capture/.env`. |
| `CAPTURE_DASHBOARD_TOKEN` | Separate secret for human operators logging into `/capture` |
| `KNOTTRA_API_KEY` / `KNOTTRA_BASE_URL` | Wiki → Knottra credentials (never touch the capture PC) |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | Powers `/api/aim` (camera auto-aim) and ASR correction |

If any are missing, this is a first-time backend setup, not a new-PC
onboarding — see `harbour-wiki/app/api/capture/*/route.ts` and
`harbour-wiki/lib/db.ts` for what each one gates, and set them with
`railway variables --service harbour-wiki --set KEY=value`. Do not invent
new tokens if other PCs are already configured with existing ones.

Confirm the deployed service is actually current (see Known Issue #4 —
Railway deploys can silently serve stale code):

```powershell
railway status
# harbour-wiki and knottra should both show "Online" with no "Deploy failed"
```

## 3. Clone and install on the classroom PC

```powershell
git clone --recurse-submodules https://github.com/harbourspace-org/harbour-wiki.git
cd harbour-wiki\capture
uv sync
```

`uv sync` installs everything, including `faster-whisper`, `opencv`,
`pyvirtualcam`, and `pywin32`. First real run downloads the Whisper model
(`small.en` by default — few hundred MB).

## 4. Configure `.env`

```powershell
copy .env.example .env
notepad .env
```

Set:

```
HARBOUR_WIKI_BASE_URL=https://harbour-wiki-production.up.railway.app
CAPTURE_TOKEN=<same value as the wiki's CAPTURE_TOKEN — ask whoever has Railway access>
```

Leave everything else commented/default unless you have a specific reason
(weak PC → smaller Whisper model, non-English lectures, a non-default audio
device index — see the table in `capture/README.md`).

## 5. Pick the microphone

```powershell
uv run python -m sounddevice
```

Note the index of the room's real microphone (not a webcam mic, not
"Default"). Put it in `.env` as `AUDIO_DEVICE=<N>` if it isn't already the
system default. In Windows' microphone properties, disable **"Allow
applications to take exclusive control of this device"** — Zoom and the
recorder both need concurrent access to the physical mic (unlike the camera,
which needs the opposite — see Known Issue #1).

## 6. Find the camera device index

```powershell
uv run python -m lecture_capture.camera_cli --list-devices
```

Note which index opens successfully and its resolution. Usually `0`.

## 7. Install OBS Studio (for the Zoom-sharing feature only)

Skip this step entirely if this room never needs to mirror the tracked
camera feed into a Zoom call — `share_with_zoom: false` in the schedule (see
§9) avoids all of this.

```powershell
winget install --id OBSProject.OBSStudio --silent --accept-package-agreements --accept-source-agreements
```

- Do **not** launch OBS and click "Start Virtual Camera" yourself, and do
  **not** run `obs64.exe --startvirtualcam`. `lecture-capture` (via
  `pyvirtualcam`) needs to be the *only* producer on that virtual-camera
  pipe — if OBS's own instance is also feeding it, they conflict and neither
  gets a clean stream. Just having OBS **installed** is what registers the
  virtual-camera driver; OBS itself should stay closed.
- The very first time `lecture-capture` tries to start the virtual camera on
  a fresh OBS install, it sometimes fails with `virtual camera output could
  not be started` even though the device is now *found* (that error text
  itself changes from "device not found" to "output could not be started" —
  that's real progress, not the same failure). This is the driver's
  one-time kernel-level registration not having fully completed. **A reboot
  after installing OBS reliably fixes this** if it doesn't work on the first
  try. It appears to need admin rights to complete on the first launch;
  without them, plan for a reboot.
- In Zoom, always select **"OBS Virtual Camera"**, never the physical
  Logitech camera directly — see Known Issue #1 for why.

## 8. Register as a wiki-managed agent

Pick a short, stable `agent-id` for this room (letters/digits/`._-` only,
e.g. the room name — `cyberspace`, `bcn-hyper`, etc).

```powershell
cd harbour-wiki\capture
uv run lecture-scheduler install-agent --agent-id <room-id> --workdir "<full path to capture folder>"
```

This registers a Windows Task Scheduler entry (`ONLOGON` trigger) so the
agent starts automatically at login and starts recording whenever the
operator-pushed schedule says so — no manual step on lecture day.

**If this fails with `Access is denied`** (common on locked-down classroom
accounts — `schtasks /Create` needs elevation there even for an `ONLOGON`
trigger under the current user), don't give up on auto-start: use the
**per-user Startup folder** instead. It needs no special privilege at all —
it's a plain folder Explorer scans at every login, not a privileged API —
and confirmed to work on an account where Task Scheduler was fully blocked.

```powershell
# install-agent (even though it failed) already wrote a launcher .cmd here:
Get-Content "$env:USERPROFILE\.lecture-capture\run-agent.cmd"
# if it's missing, create it yourself:
@"
@echo off
cd /d "<full path to capture folder>"
"<full path to capture folder>\.venv\Scripts\python.exe" -m lecture_capture.scheduler agent --agent-id "<room-id>" --workdir "<full path to capture folder>" >> "$env:USERPROFILE\.lecture-capture\scheduler.log" 2>&1
"@ | Set-Content "$env:USERPROFILE\.lecture-capture\run-agent.cmd" -Encoding ascii

# a plain .cmd in Startup flashes a console window at every login — wrap it
# in a tiny VBScript that launches hidden (window style 0):
@"
Set shell = CreateObject("WScript.Shell")
shell.Run """$env:USERPROFILE\.lecture-capture\run-agent.cmd""", 0, False
"@ | Set-Content "$env:USERPROFILE\.lecture-capture\run-agent-hidden.vbs" -Encoding ascii

# Windows executes .vbs files placed directly in Startup — no shortcut needed:
Copy-Item "$env:USERPROFILE\.lecture-capture\run-agent-hidden.vbs" `
  -Destination "$([Environment]::GetFolderPath('Startup'))\lecture-capture-agent.vbs" -Force
```

This runs hidden at every login, no admin required, no visible window, no
manual step on lecture day — a full substitute for `install-agent` on
accounts where Task Scheduler is locked down. Test it once by logging off
and back on (or rebooting) and checking the agent shows up on the
dashboard; **don't run it manually first and then also let it start at
next login** — that creates two competing processes fighting over the same
camera/mic (see Known Issue #1's cousin: duplicate agent instances cause
the exact same device-contention symptoms as the Logi Sync conflict, but
from our own leftover process instead).

Only if *both* Task Scheduler and the Startup folder are unavailable
(rare — would mean this account can't run background processes on login at
all) do you fall back to a fully manual, no-persistence run:

```powershell
uv run lecture-scheduler agent --agent-id <room-id> --workdir "<full path to capture folder>"
```

Leave this running for the whole class. It will not survive a reboot or
logout — someone has to relaunch it. This is the least reliable option;
prefer the Startup-folder method above whenever Task Scheduler is blocked.

## 9. Push a schedule from the operator dashboard

Once the agent process is running, it shows up on the dashboard within a
few seconds, status `waiting-schedule`:

```
https://harbour-wiki-production.up.railway.app/capture
```

Log in with `CAPTURE_DASHBOARD_TOKEN`. Paste a schedule JSON for this
`agent-id`, or POST it directly:

```powershell
$headers = @{ Authorization = "Bearer <CAPTURE_DASHBOARD_TOKEN>" }
$body = @{
  agentId = "<room-id>"
  schedule = @{
    weeks = 1
    camera = @{
      device          = 0        # from step 6
      enabled         = $true
      share_with_zoom = $true    # false if this room never needs Zoom mirroring (skips step 7 entirely)
      flip_180        = $false   # true if the PTZ camera is physically mounted upside down (see step 10)
      modality        = "board"  # "board" | "slide" | "desk" — see Known Issue #7 before picking "desk"
    }
    lessons = @(
      @{ day = "monday";  slot = 1; week = 1; course = "Algorithms";  course_id = "ALG101" }
      @{ day = "tuesday"; slot = 2; week = 1; course = "Databases";   course_id = "DB101"  }
    )
    timezone   = "Europe/Madrid"
    start_date = "2026-09-07"   # Monday of week 1
  }
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "https://harbour-wiki-production.up.railway.app/api/capture/schedule" `
  -Method POST -Headers $headers -ContentType "application/json" -Body $body
```

Slots are fixed: `1` = 09:00–12:30, `2` = 13:00–16:30, `3` = 17:00–20:30
(local `timezone`). The agent hot-reloads a schedule change **for the next
lesson it starts** — but see Known Issue #3 if you change camera config
(`flip_180`, `modality`, `share_with_zoom`) **while a lesson is already
recording**: that requires a full agent restart to take effect, not just a
new schedule push.

## 10. Calibrate the camera

While the very first lesson is live (or run `lecture-camera --preview`
standalone to check without waiting for a schedule slot):

- **Rotation**: if the live feed (Zoom's OBS Virtual Camera, or `--preview`)
  is upside down, set `camera.flip_180: true` in the schedule and do a full
  agent restart (§ Known Issue #3). This corrects both the Zoom feed and the
  frames sent to Knottra.
- **Pan/tilt direction**: if the camera visibly moves the wrong way when
  tracking, set `pan_sign: -1` and/or `tilt_sign: -1` in `camera`.
- **Audience masking**: default masks the lower 38% of frame. Override with
  `audience_zones` (list of normalized `[x,y]` polygons) if the room layout
  puts seating somewhere else.

## 11. Verify everything end-to-end

Don't trust "no errors printed" — actively check each hop.

**Dashboard status** (also visible in the browser at `/capture`):

```powershell
$headers = @{ Authorization = "Bearer <CAPTURE_DASHBOARD_TOKEN>" }
$r = Invoke-RestMethod -Uri "https://harbour-wiki-production.up.railway.app/api/capture/control" -Headers $headers
$r.agents | Where-Object { $_.agent_id -eq "<room-id>" } | ConvertTo-Json -Depth 6
# expect: scheduler_status "recording", audio_status/camera_status "running",
# outbox_pending 0, errors [] once a lesson is active
```

**Local outbox** (should always drain to 0 quickly — a growing count means
delivery is failing, not that nothing is being captured):

```powershell
uv run python -c @"
import sqlite3, os
con = sqlite3.connect(os.path.expanduser('~/.lecture-capture/outbox.sqlite3'))
print(con.execute('SELECT COUNT(*) FROM pending_events').fetchone())
"@
```

**Knottra actually received and fused it** (needs `KNOTTRA_API_KEY` /
`KNOTTRA_BASE_URL` — ask whoever has Railway access, don't hardcode in any
committed file):

```powershell
$headers = @{ "X-API-Key" = "<KNOTTRA_API_KEY>" }
Invoke-RestMethod -Uri "<KNOTTRA_BASE_URL>/v1/sessions/<course_id>--l<NN>/record" -Headers $headers | ConvertTo-Json -Depth 8
```

`fused_through_seq` should climb over time; `concepts` should reflect actual
lecture content, not a stale/empty result. If a concept's `detail` describes
something the camera clearly isn't looking at, see Known Issue #7 — that's a
tracking/framing problem, not a delivery failure.

**Logs to tail if anything looks wrong** (all in `~/.lecture-capture/`):
`scheduler.log`, `recorder.log`, `camera.log`.

## 12. Known issues & fixes (read before you hit them)

### 1. Camera "Insufficient system resources" / "Cannot open camera device N" / infinite "frame grab failed; retrying"
Almost always a **Logitech Options+/Logi Sync** conflict on a PC with a
Logitech PTZ camera — that software holds an exclusive lock on the camera.
Symptoms:
- On startup: DirectShow error `-2147023446 'Insufficient system resources
  exist to complete the requested service'`, then `Cannot open camera device
  N` from the cv2 fallback too — the camera never opens at all.
- Mid-recording (often right when Zoom, or anything else, touches any
  camera on the system): `frame grab failed; retrying …` forever. The
  capture code's retry loop does **not** reopen the device — it just keeps
  calling `read()` on an already-dead handle. **This never self-heals. Only
  a process restart (kill the `camera_cli` process tree, let the scheduler
  relaunch it) or a full agent restart fixes it once it happens.**

Fix ladder, cheapest first:
1. Kill the user-mode process: `Stop-Process -Name logioptionsplus_agent -Force`.
   Sometimes enough on its own.
2. If it recurs immediately even after that, the lock is coming from
   Logitech's **background services** — `LogiSyncHandler`,
   `LogiSyncMiddleware`, `LogiSyncProxy` (parent process is a system service
   host, PID ~600). These reject `Stop-Process`/`taskkill` with `Access is
   denied` from a non-admin account — there is no user-mode workaround.
3. **A full PC reboot reliably clears it** (confirmed: killing the
   processes alone was insufficient once; a reboot fixed it completely).
4. The real long-term fix, if this PC is dedicated to lecture capture:
   uninstall Logi Options+/Logi Sync entirely, or disable their services
   from auto-starting (needs admin).

### 2. Same symptom, but you already restarted and it's still failing immediately
The device may be genuinely gone from Windows' device tree for a moment
(`Get-PnpDevice` narrow filters can also just be checking the wrong `Class`
— this camera enumerates under `Class: Image`, not `Class: Camera`; check
both, or filter by `FriendlyName` instead). If the device is present with
`Status: OK` but a *brand-new* process still can't open it, the lock is
services-level (see #1, step 2/3) — a reboot is the only remaining lever
short of admin rights.

### 3. Pushing a schedule change doesn't change running behavior
The scheduler reads `schedule.camera` and builds the `camera_cli` command
line **once, when a lesson starts** — it does not hot-reload `flip_180`,
`share_with_zoom`, `modality`, `device`, etc. into an already-running
camera process, even if you restart just that one subprocess. To apply a
camera config change mid-lesson:

```powershell
# Kill the ENTIRE process tree (top-level agent + its audio + camera children),
# not just camera_cli, or you'll get duplicate/orphaned processes fighting
# over the same camera device.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "lecture_capture|lecture-scheduler" } |
  Select-Object -ExpandProperty ProcessId | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# relaunch
cd harbour-wiki\capture
uv run lecture-scheduler agent --agent-id <room-id> --workdir "<full path>"
```

Verify the new launch actually picked up the change by checking the
relaunched `camera_cli` process's command line includes the expected flag
(e.g. `--flip-180`) before assuming it worked.

### 4. Knottra silently serves stale code after a deploy
`railway redeploy` (without `--from-source`) just restarts the **existing**
build — it will not pick up new commits ever. `railway redeploy
--from-source` and even `railway up` from a local checkout can *still* fail
to pick up the current commit if the service's GitHub source connection is
pinned to an old ref rather than tracking the branch tip — a deploy can
report `SUCCESS` while still serving old code. (`railway up` may also
outright fail by defaulting to the wrong builder — Nixpacks/Railpack
instead of the `Dockerfile` builder `knottra/railway.json` specifies —
check `railway status` for `Deploy failed` after running it.)

**Reliable fix**: re-point the service's source explicitly, which forces a
correct rebuild from the branch tip using the repo's own `railway.json`:

```powershell
railway service source connect --repo harbourspace-org/knottra --branch main --service knottra
```

**Always verify with a real API call after any deploy**, never trust the
deploy status alone — e.g. POST a test event with a `client_event_id` and
confirm it's accepted (`202`), not rejected with a schema error that implies
the deployed contract is older than what you expect.

### 5. Task Scheduler `install-agent` fails with "Access is denied"
`schtasks /Create` needs elevation on some locked-down classroom PCs even
for an `ONLOGON` trigger under the *current* user — there is no way to fix
`schtasks` itself without admin rights. **This is not the dead end it looks
like**: use the Startup-folder method in step 8 instead (a hidden `.vbs` in
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) — confirmed to
work with zero admin rights on a PC where Task Scheduler was fully blocked,
and it gives the same "starts automatically at login, no manual step"
result. Only fall back to a fully manual `uv run lecture-scheduler agent
...` run (no persistence across reboot/logout at all) if that also somehow
doesn't work.

### 6. `/api/aim` returns persistent 502s
This only affects the PTZ **auto-aim/teacher-tracking** quality (Claude
looking at a room screenshot to say where the lecturer/board is) — it does
not block recording, delivery, or fusion of either modality. Local YOLO
detection still works without it. If a room doesn't need auto-tracking
(fixed camera, or you're fine with the default framing), this is safe to
ignore. If it matters, check `LLM_API_KEY`/`LLM_BASE_URL` on the
`harbour-wiki` service and the wiki's own logs for the actual error.

### 7. `modality: "desk"` doesn't mean "point the camera at a static desk"
It's a **deprecated alias** that still enables full teacher-tracking
(`follow_teacher`) — the camera scouts for a standing lecturer and frames
whatever board-like surface is near them, not literally "the desk." For an
unattended solo demo (someone sitting still, writing on a desk, no one
"teaching"), this mode may never confirm a stable crop, or may stay locked
onto whatever surface it detected earliest in the session (e.g. a
projector slide from minutes ago) instead of adapting to new content. There
is a purpose-built `follow_local` CLI mode ("single-person/demo use only,"
no teacher-tracking, no `/api/aim` calls) but **it is not currently wired
into the schedule config** — only reachable by running `camera_cli`
manually with `--follow-local` outside the scheduler. If solo-desk demos are
a real use case for this deployment, add a `follow_local` key to the
`booleans` mapping in `scheduler.py`'s `_camera_args` (mirrors how
`follow_teacher` is already wired) rather than fighting teacher-tracking
mode.

### 8. General tooling note for whoever (or whichever Claude) operates this PC
- Prefer the PowerShell tool over Bash for everything on these classroom
  PCs — Git Bash here is often a minimal build lacking `grep`/`sed`/`head`/
  `which`/`powershell.exe`-on-PATH, and its `PATH` uses Windows-style
  backslash-separated entries that bash doesn't parse, so `node`, `uv`, and
  `railway` frequently aren't resolvable from it even though they work fine
  from PowerShell.
- Killing/restarting processes and rebooting the PC are the two most
  common real fixes in this whole document. Confirm before rebooting if a
  lesson is actively recording — it's disruptive and ends the session, but
  the durable SQLite outbox means no data is lost, and the scheduler resumes
  the same lecture on restart if it's still within the active slot.
