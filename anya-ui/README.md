# Anya's app

Anya's own chat window — a clean, local-first front-end with **saved history**, a
**power/memory limiter** so you can leave her running while you play a game,
optional **web browsing** you switch on and off yourself, and a **Projects** tab
where she writes real files and builds installable Android APKs.

Everything here is **standard-library Python and plain HTML** — no packages to
install, nothing to keep up to date.

```
anya-ui\
  anya_ui.py     the app: web server + chat history + model supervisor
  index.html     the interface (all CSS/JS inline, no CDNs)
  web.py         optional web browsing: search + page reading (stdlib only)
  projects.py    the Projects sandbox: files, tasks, commands, APK builds
  start.ps1      one-click launcher (the desktop icon points here)
  selftest.py    end-to-end check of chat + history + export (+ --web/--build)
  config.json    your settings (created on first run)
  anya_chats.db  every conversation, in SQLite
  current.txt    which project the tab is focused on
  approvals.json writes waiting for your OK
```

---

## Starting it

**Easiest:** double-click **`Anya`** on the desktop. A window opens with the app.
The second click is instant — it reuses the running app instead of restarting it.

Or:

```powershell
# from the project folder
.\anya-ui\start.ps1                  # same as the desktop icon
S:\envs\ai\Scripts\python.exe anya-ui\anya_ui.py   # run it directly, in a console
```

The app listens on **<http://127.0.0.1:8091>** (the model itself is served
separately, on port 8090). It stays running after you close the window, so
reopening is instant. To shut it down completely, stop the Python process (or
close it from Task Manager); the model is stopped with it.

---

## The window

- **Left sidebar** — every past chat, newest first. Click one to read it, use the
  search box to find something, `×` to delete. `New chat` starts fresh.
- **Chat** — replies stream in as she writes them. Code arrives in fenced blocks
  with a language label and a **Copy** button. `Enter` sends, `Shift+Enter` makes
  a new line, and the ■ button stops a reply mid-flight.
- **Top-right buttons** — **🌐 Web** turns internet access on and off (below);
  **🗂 Projects** opens the Projects tab (below); the **Power** button opens the
  Power panel and Settings.
- **Export** — appears once a chat has messages; downloads it as Markdown.

Keyboard: `Ctrl+K` search · `Ctrl+Shift+O` new chat · `Esc` close the panel.

---

## Web browsing (optional)

Off by default. The **🌐 Web** button in the header turns it on: the label flips
to **Web on**, the dot turns green, and the footnote under the composer changes
from *"Offline model"* to *"Web browsing is on"*. Nothing touches the network
while it is off, and Anya — correctly — tells you she is offline.

Anya is a 1.5B model with **no trained function-calling**, so browsing is driven
by the app, not by her good judgement. There are three paths:

| Path | Trigger | Depends on the model? |
|---|---|---|
| **Open a link** | the message contains a URL (`http(s)://…` or `www.…`) | no |
| **Search** | the message asks for it — *"search the web for X"*, *"look up X"*, *"google X"* — or asks about something that changes (*"the newest version of X"*, *"how much does X cost"*, *"the weather"*) | no |
| **Ask for a lookup** | she replies with `{"name": "web_search", "arguments": {"query": "…"}}` or `{"name": "web_open", "arguments": {"url": "…"}}` | yes (best-effort) |

The first two are what you rely on; the third is a bonus. `web.py` owns both the
triggers (`wants_search`, `search_query_from`, `find_urls`) and the tool-call
parser (`parse_tool_call`), so it can be reasoned about and tested on its own.

**What happens during a reply**

- The app runs the lookup, streams a small **step chip** into the message
  (*"Searching the web — jetpack compose"*, *"Read a page — developer.android.com"*),
  then feeds Anya the results and lets her answer.
- She is told to reply with **only** a JSON tool call when she wants one, so the
  plumbing is never shown: a small streaming filter watches her output and swallows
  a JSON object that names a tool — wherever it appears, with or without a code
  fence, and even when she puts a sentence in front of it. Everything else streams
  through untouched, and the reply saved to history is exactly what you saw.
- Every reply that used the web ends with a **Sources** list. If she forgot to
  cite a page she was given, the app appends the list, so sources are always in
  the saved history and the Markdown export.
- Repeated lookups in one turn are cached (and failures are remembered), so she
  cannot make you fetch the same URL three times.

**Safety and limits**

- Public `http`/`https` only. `localhost`, loopback, private, link-local and
  `file://` targets are refused before any request is made.
- 400 KB and 20 seconds per page; text is reduced to plain prose, keeping
  `<main>`/`<article>` where a page has one.
- Search uses **DuckDuckGo** (`html.duckduckgo.com`, falling back to
  `lite.duckduckgo.com`). No key, no account. A shared cookie jar is used,
  because many real sites bounce you through a redirect that needs it.
- Pages are truncated to the **Text kept per page** setting (default 1 400
  chars). *Balanced* is only 4 096 tokens of context, so keep it small; *Turbo*
  (8 192) has room for more.

---

## Projects — she writes files and builds APKs

The **🗂 Projects** button in the header (and the *Projects* tab in the side panel)
is where Anya actually *makes* things instead of just describing them: she can
create a project, write and read real files in it, keep a task list, and build an
**installable Android APK**.

Everything she writes lives in one folder — **`S:\anya-projects`** by default —
managed by `projects.py`. This is the sandbox: nothing she does can reach outside
it. A build writes an APK at `…/<project>/app/build/outputs/apk/debug/app-debug.apk`.

### The tab

The panel has a **Projects** tab that shows exactly what she is working on:

- **Current work** — the project the tab is focused on, its name, and its status.
- **Projects** — every project, newest first. Click one to focus it (that is what
  *"her current project"* means, and it survives restarts in `current.txt`).
- **Project detail** — the **task list** (add, click to move `todo → doing → done`,
  or cycle), the **file tree**, and a viewer to open a file.
- **One project** — its **task list** (add; click to move `todo → doing → done`),
  its **file tree**, and a viewer to open a file. Three buttons sit under it:
  **Open folder** (shows the project in Windows Explorer), **Keep working** and
  **Delete** (removes the project and all its files, after a confirmation).
- **History / activity** — every action logged against the project (created,
  wrote a file, ran a command, built), so you can see what she has been doing.
- **Approvals** — writes that pointed outside the workspace, waiting for you to
  **Approve** or **Deny**.

The chat and the tab are the same thing seen two ways: when she creates a project
or builds in chat, the tab updates on its own (it polls `/api/status`).

### Working unattended

**Keep working** runs her without you prompting each step. Give it a goal (or
leave it blank) and she loops — read, write, plan, build — feeding each result
into the next step, with the run streamed into the **Unattended work** log. It
stops when she is done, when she starts repeating herself, or after the step
budget; the button becomes **Stop working** while it runs, and everything still
passes through the same sandbox and approval rules.

### Asking for one

Just say what you want, in chat:

> Make me a small Android app called Dice Roller, then build the APK.

She creates the project from a **working Android Studio scaffold** (so the very
first build succeeds), then assembles a **debug APK** — auto-signed and ready to
`adb install`. Steps appear in the message as small chips
(*"Created project — dice-roller"*, *"Building the APK"*), and the Gradle log
streams into the tab while it runs.

You can also use the tab directly: **New project**, add tasks, then **Build**.

### What she may do

`projects.py` is the only thing that touches the disk, and it enforces:

- **Writes stay inside the project.** A relative path that escapes, or a
  `..` in any path, is refused outright. An *absolute* path outside the workspace
  is not silently refused — it is turned into a **pending approval** you see in the
  tab, and nothing is written until you approve.
- **Commands are from a fixed list** — `gradlew`, `gradle`, `java`, `javac`,
  `kotlinc`, `python`, `git`, `adb`, `aapt2`, `apksigner`, … — and are run from a
  row you could have typed yourself: shell metacharacters (`; | & > < $`) and
  `rm`/`del`/`rd`/`format` are rejected before anything runs.
- **`build_apk` is the build.** She is steered to it and away from calling Gradle by
  hand; it uses the Android Studio JBR and SDK already on this PC.
- Skipped: `build`, `.gradle`, `.idea`, `.git`, `.anya`, `node_modules`.

Projects are on by default and governed by the same philosophy as the Web switch —
you can turn them off, or move the workspace, in **Settings**.

---

## Power & memory (the gaming part)

The panel's **Power** tab trades speed against memory. Changing a profile reloads
the model, which takes a few seconds (the window shows progress).

| Profile | GPU layers | Context | Anya's VRAM | Anya's RAM | Notes |
|---|---|---|---|---|---|
| **Turbo** | all 28 | 8 192 | ≈ 3.1 GB | ≈ 0.55 GB | fastest when nothing else is using the GPU |
| **Balanced** | 24 | 4 096 | ≈ 2.6 GB | ≈ 0.9 GB | good default |
| **Lite** | 8 | 4 096 | ≈ 1.2 GB | ≈ 2.4 GB | small VRAM footprint |
| **CPU only** | 0 | 2 048 | ≈ 0.08 GB | ≈ 3.0 GB | **best while gaming** |
| **Off** | — | — | 0 | 0 | stops the model, frees everything |

Those figures are **measured on this PC** (they come from llama.cpp's own memory
report) — the panel shows live numbers and refreshes them whenever a profile
starts.

**Fine tune** lets you go beyond the presets: a GPU-layer slider (0–28), context
length (1 024–16 384) and CPU-thread count. Fewer CPU threads (2–4) keeps games
smooth when Anya is on the CPU.

**Auto-unload** stops the model after N minutes of silence, so it never holds
memory while you are away. The next message reloads it automatically.

### Playing a game? Use CPU only.

This is the important bit, and it is measured, not guessed. On an 8 GB card the
game and Anya fight over the same VRAM, and Windows pages one of them in and out:

| Profile | Speed **while a game is running** |
|---|---|
| CPU only | **11.1 tok/s** |
| Balanced | 2.9 tok/s |
| Turbo | 1.8 tok/s |

So the GPU modes are *faster only when the GPU is free*. With a game up, putting
her on the CPU is several times quicker **and** hands the whole card back to the
game. For the biggest win, press **Off** — that frees ~3 GB of VRAM and ~3 GB of
RAM.

---

## Settings

- **System prompt** — her persona. Edit it and every new message uses it.
- **Creativity (temperature)** — 0 is focused and repeatable, 1 is loose.
- **Offline switch** — choose the backend: `llama-server` (the one with the
  memory controls) or `Ollama` (the `anya` model you already have).
- **Web browsing** — the on/off switch, lookups per reply, and text kept per page.
- **Projects** — whether she may create projects, write files and run builds, and
  where the workspace lives (`S:\anya-projects`).
- **Phone access** — reach her from your phone: the switch, how you get there
  (this Wi-Fi / Tailscale / Cloudflare tunnel), the QR code and the key.
- **Updates** — check GitHub for a newer release and update in place.

Changes are saved to `config.json` and survive restarts.

---

## Anya on your phone

Flip on **Phone access** in Settings and Anya also listens on your network, so a
phone on the same Wi-Fi can open her. The panel shows a **QR code** — scan it
with the phone's camera and you're in. Requests from this PC are always allowed;
a phone must present the **key**, which the scanned link supplies (and which is
then stored as a cookie, so you only do it once per device).

Three ways to reach her:

- **This Wi-Fi** — the plain LAN address, e.g. `http://192.168.1.177:8091`.
- **Tailscale** — if Tailscale is installed, its address is detected and offered,
  so it works over mobile data with no port-forwarding.
- **Cloudflare tunnel** — works from anywhere with no account; Anya offers to
  download `cloudflared` and start/stop the tunnel for you.

Press **New key** to roll the key (every phone must then be re-added). Turn the
switch off to go back to this-PC-only. The QR is generated locally by `qr.py` —
nothing is sent anywhere.

---

## The mobile UI

There is no separate phone app: **the same page adapts**. On a phone the sidebar
becomes a slide-in drawer (tap the scrim or pick a chat to close it), the top bar
drops its labels, the Settings panel goes full-width, the composer clears the home
bar, and text boxes are 16 px so iOS never zooms on focus. There is no horizontal
scrolling at 360 px or 390 px, and a browser that blocks storage still boots.

---

## Updating Anya

**Settings → Updates → Check for updates** reads the newest release from GitHub
and compares it to `VERSION`. If there's something newer, press **Update now**:

- a `git`-cloned copy fast-forward pulls;
- a ZIP download gets the release laid over the source.

Either way your `config.json`, chats (`anya_chats.db`), approvals, models, LoRA
adapters, training data, library and projects are **never touched**, and Anya
restarts herself when it's done.

---

## Voice — talk to her, and let her talk back

The **mic** button in the composer records a message; the **speaker** button reads
a reply aloud. Speech in is **whisper** (`openai-whisper`, the `small.en` model
under `S:\voices\whisper`); speech out is **piper** (`en_US-lessac-medium` under
`S:\voices\piper`). Both are optional and lazy: nothing is loaded until you first
use them, and both unload after four minutes of silence so they never hold VRAM
while you game. The browser records 16 kHz mono WAV itself, so no `ffmpeg` is
needed, and speech-to-text runs on the **CPU** by default (`voice_device`), which
keeps it clear of the model's VRAM. The Settings tab has the on/off switches, the
model/voice pickers and the device.

---

## Choosing the model (bigger = smarter, hungrier)

The **Power** panel's **Model** section lists every `.gguf` in `S:\models`. Pick
one and press **Apply**; the app reloads with that file. Layer counts are read
straight from each file's GGUF header, so the **ngl** slider's maximum always
matches the model you loaded, and the power profiles are stored as *fractions* of
the layer count — switching from the 1.5B to a 7B retunes them automatically. A
7B (`Qwen2.5-Coder-7B-Instruct Q4_K_M`) gives markedly better answers; the 1.5B
stays the fast, low-VRAM choice.

---

## Long-term memory

Anya keeps a short list of durable facts about you and carries them into every
chat. The **Memory** tab shows them; you can add a fact, delete one, or clear the
lot. Facts live in one JSON file (`S:\anya-memory\memory.json`) you can read or
back up.

- She learns in the background after each exchange: the app has conservative
  patterns for the obvious things (*"my name is…"*, *"I'm working on…"*) and can
  ask the model for more.
- **Grounding filter** — a weak model likes to invent memories ("User lives in
  Berlin"). A candidate is only stored if the words that make it distinctive
  actually appear in *your* message, so invented facts are thrown away.
- Near-duplicates are merged, so *"is working on a weather app"* and *"works on a
  weather app"* stay one memory.
- Two switches in the tab turn the whole thing on/off and the background learning
  on/off.

---

## Where your chats live

Everything is in **`anya-ui\anya_chats.db`** (SQLite). A chat is only created once
you send the first message, and its title becomes your first message, trimmed.

- Export a single chat: the **Export** button, or `GET /api/export/<id>`
- Back the lot up: just copy `anya_chats.db`

---

## Using it from your own scripts

The same HTTP API the window uses:

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/status` | profile, VRAM/RAM, speed, running state |
| `POST` | `/api/profile` | `{"profile":"cpu"}` — switch power profile |
| `POST` | `/api/chat` | `{"session_id":…, "message":…}` — streams Server-Sent Events |
| `GET` | `/api/sessions` | list chats (`?q=` to search) |
| `GET` | `/api/sessions/<id>` | one chat with all its messages |
| `DELETE` | `/api/sessions/<id>` | delete a chat |
| `GET` | `/api/export/<id>` | the chat as Markdown |
| `POST` | `/api/settings` | system prompt, temperature, auto-unload, backend, web, projects |
| `GET` | `/api/projects` | list projects + workspace root + current |
| `POST` | `/api/projects` | `{"name":"…","kind":"android"}` — create one |
| `GET` | `/api/projects/<pid>` | one project (tasks, activity, last build) |
| `DELETE` | `/api/projects/<pid>` | delete a project |
| `GET` | `/api/projects/<pid>/file?path=…` | read a file from the project |
| `POST` | `/api/projects/<pid>/task` | add a task, or set one's status |
| `POST` | `/api/projects/<pid>/current` | focus this project |
| `POST` | `/api/projects/<pid>/build` | assemble the APK (streams the log) |
| `GET` | `/api/approvals` | writes waiting for your OK |
| `POST` | `/api/approvals/<id>` | `{"approve":true}` or `false` |
| `GET` | `/api/models` | every `.gguf` in the models folder, with layer count and which is active |
| `POST` | `/api/models/select` | `{"path":"…"}` — reload with that model |
| `GET` | `/api/memory` | stored facts + the enabled/learning switches |
| `POST` | `/api/memory` | `{"text":"…"}` to remember one, `{"clear":true}` to forget all |
| `DELETE` | `/api/memory/<id>` | forget one fact |
| `GET` | `/api/voice` | speech models on disk + the switches |
| `POST` | `/api/voice/stt` | raw 16 kHz mono WAV body → `{"text":"…"}` |
| `POST` | `/api/voice/tts` | `{"text":"…"}` → a WAV file |
| `GET` | `/api/health` | liveness + version (never needs the key) |
| `GET` | `/api/remote` | phone-access state: URLs, QR payload, tunnel status |
| `POST` | `/api/remote` | turn phone access on/off, change tunnel, roll the key |
| `GET` | `/api/remote/qr.png` | the QR code as a PNG |
| `POST` | `/api/remote/tunnel` | `{"action":"install"\|"start"\|"stop"}` |
| `GET` | `/api/update` | newest GitHub release vs `VERSION` |
| `POST` | `/api/update/apply` | apply the update (git pull or zip overlay) |
| `POST` | `/api/restart` | restart the server |

Quick example:

```powershell
# switch to CPU-only before gaming
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8091/api/profile `
  -ContentType application/json -Body '{"profile":"cpu"}'
```

`/api/status` also reports `web_enabled`, `web_max_pages` and `web_chars`, plus a
`projects` block: the workspace root, the focused project, the project list, its
tasks and last build, the activity feed, and how many approvals are waiting.

### `/api/settings` keys

Any subset; unknown keys are ignored.

| Key | Default | Meaning |
|---|---|---|
| `web_enabled` | `false` | master switch for all browsing |
| `web_max_pages` | 3 | lookups (searches/pages) allowed per reply, 1–6 |
| `web_chars` | 1400 | characters kept from each page, 400–6000 |
| `projects_enabled` | `true` | can she create projects, write files and run builds |
| `projects_root` | `S:\anya-projects` | the one folder she may write inside |
| `voice_stt` | `true` | allow the microphone to transcribe |
| `voice_tts` | `false` | read replies aloud automatically |
| `voice_stt_model` | `small.en` | which whisper model to use |
| `voice_piper_voice` | `en_US-lessac-medium` | which piper voice to speak with |
| `voice_device` | `cpu` | `cpu` or `cuda` for speech-to-text |
| `memory_enabled` | `true` | carry remembered facts into every chat |
| `memory_learn` | `true` | learn new facts in the background |
| `memory_inject` | `30` | most facts injected into one message |
| `memory_dir` | `S:\anya-memory` | where the facts file lives |
| `remote_enabled` | `false` | also listen on the network so a phone can reach her |
| `remote_token` | (generated) | the shared key a phone must present |
| `remote_tunnel` | `false` | use a Cloudflare quick tunnel for access from anywhere |
| `remote_tunnel_on_start` | `false` | start the tunnel automatically with the app |

### `/api/chat` streaming events

Each `data:` line is one JSON object:

| `type` | Payload |
|---|---|
| `start` | `session_id` |
| `token` | `text` — a piece of the answer (real answer text only, never plumbing) |
| `tool` | `state` (`start`/`done`), `name` (`web_search`/`web_open`/project tools), `detail`, `ok` |
| `done` | `message_id`, `tokens`, `tps`, `title` |
| `error` | `message` |

---

## Checking it still works

```powershell
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py          # offline checks
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py --web    # also the web paths
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py --build  # also a real APK build
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py --voice  # also a piper → whisper round-trip
```

It drives the real API: sends a conversational message, asks for Kotlin code,
verifies the chat was saved, searches it, exports it and deletes it. A pass means
the window has everything it needs. Run it after any retraining or redeploy.
`--web` adds a pasted-link fetch, a search and a "no lookup for plain chat" check
(needs internet; it restores your Web setting afterwards). `--build` additionally
creates a throwaway Android project and assembles a real APK (slow; it cleans up
after itself either way). Project checks — the sandbox, the file/task/approval
paths, the trigger phrases and the tool-JSON parser — always run, and the memory
store (add / ignore duplicate / forget), model discovery, the phone-access
helpers (addresses, key generation, QR encoding) and the updater (version
parsing, release check, and a safe-overlay test) are checked every time too.
`--voice` adds a piper-speaks-then-whisper-reads-it-back round-trip.

---

## Troubleshooting

**The window opens but says "Anya's model isn't running".**
Pick a power profile (other than *Off*) in the Power panel.

**"Model failed: llama-server exited during startup".**
Read `S:\tools\logs\llama-server.err.log`. The usual cause is a bad path in
`config.json` (`llama_server` or `gguf`).

**"port 8090 is still in use by another program".**
Something else grabbed the model's port. Close it and switch profiles again.

**The window itself won't open.**
Check that port 8091 is free: `Get-NetTCPConnection -State Listen -LocalPort 8091`.
If another Python is stuck, end it and click the icon again.
