# Anya — Feature Overview & Build Blueprint

*A local AI assistant with her own GUI, a memory throttle, optional web
browsing, and a Projects tab where she writes real files and builds Android APKs —
built to run on a single 8 GB GPU and 16 GB of RAM, and to coexist with PC
gaming.*

This document describes everything Anya does, how her interface is put together,
and the decisions (and traps) behind it, so that someone else can build or adapt
their own version.

---

## 0. The seven ideas worth stealing

1. **A small fine-tune can do two jobs.** One 1.5B model chats naturally *and*
   writes code, because the training data was mixed ~1:4 chat-to-code rather than
   being a pure coding set.
2. **A model can "know" its name** if the identity is trained in *and* reinforced
   in the system prompt. Cheap, and it changes how the assistant feels to use.
3. **A memory throttle turns a toy into a tool.** Choosing how many GPU layers a
   model uses, at runtime, is the difference between "an AI I can run" and "an AI I
   can leave running while I play games."
4. **Honest measurement beats pretty numbers.** Windows will not tell you a
   process's VRAM, so footprints are *calibrated* from anchors the model server
   itself reports — and speed is only ever displayed once actually measured.
5. **No dependencies is a feature.** The GUI is standard-library Python plus one
   HTML file. Nothing to install, nothing to break, nothing to update — the optional
   web browsing is standard library too.
6. **Put the capability on the app's side, not in the model.** A 1.5B fine-tune
   cannot be trusted with a shell, but it does not need to be: the app performs the
   writes and builds, fenced by *one* sandbox root, an **approval queue** for
   anything outside it, and a command **allow-list**. That is what makes "leave her
   working" safe rather than reckless (§5.10).
7. **Write the 200 lines instead of adding the dependency.** A QR code, a local
   update mechanism and a tunnel launcher are each "just use a library" problems —
   and each one, hand-written, keeps the app dependency-free, auditable, and
   offline. The QR encoder (`qr.py`) is byte-mode, versions 1–40, all four error
   levels, eight masks with penalty scoring, and PNG output via `zlib` — and it
   decodes, which is the only test that matters.

---

## 1. Spec sheet

| | |
|---|---|
| **Persona** | Anya |
| **Base model** | `Qwen2.5-Coder-1.5B-Instruct` (28 layers, 151,936 vocab, 1.54B params) |
| **Customisation** | QLoRA (4-bit) fine-tune → merged → **F16 GGUF** (3.1 GB) |
| **Training** | **22,442 examples** · 5,612 steps · 2 epochs · final loss **~0.37** · **2 h 59 m** |
| **Hardware** | Windows 11 · RTX 5050 (8 GB) · Core Ultra 5 225F · 16 GB DDR5 |
| **Inference** | `llama-server` (Vulkan) on `:8090`; also served by Ollama on `:11434` |
| **GUI** | her own app on `:8091` — standard-library Python + one HTML file |
| **App dependencies** | **none** — no pip installs, no frameworks, no CDNs |
| **Release** | **v0.17.0** — phone access, self-update, mobile UI, hand-rolled QR |
| **Speed** | ~72–84 tok/s on an idle GPU · 11.1 tok/s CPU-only while gaming |
| **Footprint** | 0.08–3.1 GB VRAM and 0.55–3.0 GB RAM, selectable at runtime |

---

### What Anya is **not**

Worth stating plainly, because it sets expectations:

- **Not a frontier model.** A 1.5B model is good at explanations, boilerplate,
  small functions and conversation. It is not reliable at large-scale reasoning.
- **Not an agent.** She has no trained tool-calling ability (see §5.5) — she cannot
  read or edit files in your IDE on her own. The exceptions live in *her own app*,
  where the **app** performs the action rather than the model: web lookups (§5.9)
  and work in her Projects sandbox (§5.10).
- **Offline by default.** She says so, truthfully, until you flip the **Web**
  switch in her own app.

---

## 2. Goals → decisions

| Goal | Decision | Why |
|---|---|---|
| Runs entirely on this PC | Ollama + a local `llama-server` | no API keys, no cloud, works on a plane |
| "Realises it has a name" | identity examples **and** a system prompt | training alone drifts; the prompt keeps it stable |
| Chats *and* codes | mixed chat/code dataset | a pure code model answers "how are you?" with a code block |
| Different from the stock page | own GUI (no framework) | the stock `llama.cpp` page is a debug tool, not a product |
| Usable while gaming | power profiles that resize the model | the game and the AI fight over the same 8 GB |
| No maintenance burden | standard library only | nothing to update, nothing to break |

---

## 3. The model

### 3.1 Base and method

- **Base:** `Qwen2.5-Coder-1.5B-Instruct` — small enough to train on 8 GB, strong
  at code for its size, and ships an Instruct chat template.
- **Method:** **QLoRA** (4-bit weights + LoRA adapters), via **LLaMA-Factory
  0.9.5**. Only the adapter is trained, which is what makes 8 GB viable.
- **Output:** adapter merged into the base, converted to **F16 GGUF** (3.1 GB) and
  loaded into Ollama / `llama-server`.

### 3.2 Training configuration (the numbers that mattered)

```yaml
model_name_or_path: Qwen/Qwen2.5-Coder-1.5B-Instruct
template: qwen                      # the model's own chat template
finetuning_type: lora
lora_rank: 16
lora_target: all
quantization_bit: 4                 # QLoRA — base weights held in 4-bit
cutoff_len: 512                     # keep it short; 1024 caused VRAM paging
per_device_train_batch_size: 1
gradient_accumulation_steps: 8      # effective batch size 8
learning_rate: 1.0e-4
num_train_epochs: 2.0
lr_scheduler_type: cosine
bf16: true                          # Blackwell supports bf16
gradient_checkpointing: true        # required to fit 8 GB
report_to: none
```

Three things made this fit an 8 GB card:

1. **4-bit base + LoRA** — only a few million adapter parameters get gradients.
2. **`gradient_checkpointing: true`** — trades speed for a large memory saving.
3. **Batch 1 + gradient accumulation** — same effective batch, a fraction of the
   peak memory.

> **A note on sequence length.** Training used `cutoff_len: 512`, while inference
> runs at 4096–8192 context. That is deliberate: the training sequence length is
> the single biggest lever on training VRAM, and 1024 already caused paging on this
> card. A longer training context is the first thing to spend a bigger GPU on.

### 3.3 The dataset mix

The whole point is the **blend**. Anya (v5) was trained on **22,442**
de-duplicated examples — double v4:

| Chunk | Examples | Purpose |
|---|---|---|
| `identity.jsonl` | 49 | her name, her nature, "you run offline" (the app overrides that line while Web is on) |
| `chat.jsonl` | 4,000 | **conversational ability** (human-written Dolly 15k) |
| `course.jsonl` | 145 | hand-written domain Q&A |
| `teaching.jsonl` | 7,861 | mined from 12 real teaching repos + official Kotlin docs |
| `public.jsonl` | 1,200 | general coding instructions |
| repo-mined (`cocoon`, `daijishou`, `android_*`, `code_*`) | ~9,200 | **real application code**, including ~5,900 lines mined from 12 second-wave Kotlin repos |

Identities that make this work:

- **She has a name because a file says so.** 49 examples is enough to stop her
  answering as "Qwen".
- **A chat-to-code ratio around 1:4** is what produces "chats naturally but writes
  code when asked". In practice a chat-heavy mix stops writing good code and a
  code-only mix stops chatting; this is the balance that worked here.
- **Double the data, better code.** v5 kept v4's chat balance but roughly doubled
  the mined code and teaching rows, which is where the biggest felt improvement
  landed (more idiomatic Compose/Kotlin).
- **Deduplicate.** The parts sum to well over 22,442 rows; the merged file is
  exactly that. Dupes bias the model toward whatever got repeated.

### 3.4 Rebuild pipeline (end to end)

```
datasets ──▶ combine.py ──▶ llamafactory-cli train ──▶ llamafactory-cli export
          ──▶ convert_hf_to_gguf.py --outtype f16 ──▶ ollama create <name>
```

Each arrow is a separate, testable step. The GGUF conversion is not optional if you
want `llama.cpp`/Ollama to serve the result.

> **Note:** Ollama cannot import many HF checkpoints directly. Converting to GGUF
> yourself is the reliable route, and it also gives you the single `.gguf` file
> that both runtimes and the app can share.

---

## 4. Behaviour and known limits

- A **17-prompt behaviour battery** (identity, chat, Kotlin, Python, "explain
  this", refusals) passes 17/17 against both runtimes.
- **Chat works:** "Hey, how's it going?" gets a sentence, not a code block.
- **Code works:** asking for a Kotlin `data class` gets a fenced `kotlin` block.
- **Agent/tool-calling does not work** — see §5.5. This is the most important
  limitation to design around. The optional **web browsing** in her own app works
  around it by doing the lookup in the app, not in the model (§5.9).

---

## 5. The GUI

Anya's GUI is a purpose-built single-page app. The goals were: it should feel like
*hers*, it should remember conversations, and it should expose the memory throttle
as a first-class control rather than a config file.

### 5.1 Shape

```
┌──────────────────────────┬───────────────────────────────────────────────────────────┐
│  ⬤  Anya                 │  Kotlin data class        Balanced · 14.0 tok/s  [ 🌐 ][ ⚡ ]│
│     runs on this PC      │───────────────────────────────────────────────────────────│
│                          │                                                           │
│  [ + New chat ]          │   You ▸ explain coroutines in one paragraph               │
│                          │                                                           │
│  🔍 search chats…        │   Anya ▸ Think of a suspend function as a function that   │
│                          │          can pause and resume without blocking a thread.  │
│  ── today ──────────     │                                                           │
│  ▸ Kotlin data class     │          ┌─────────────────────────────────────┐          │
│  ▸ Coroutines explained  │          │ ```kotlin                          │          │
│  ▸ JSON script           │          │ suspend fun load() { … }           │          │
│                          │          │ ```                        [ Copy ]│          │
│  ── memory ──────────    │          └─────────────────────────────────────┘          │
│  VRAM ▓▓▓▓▓▓░░░░  2.7 GB │                                                           │
│  RAM  ▓▓░░░░░░░░  0.9 GB │───────────────────────────────────────────────────────────│
│                          │  [ Type a message…                                  ] [ ■ ] │
└──────────────────────────┴───────────────────────────────────────────────────────────┘

         ⇧  the ⚡ button opens the sliding panel below
┌───────────────────────────────────────────┐
│  Power                 │  Settings          │   ← tabs
│─────────────────────────┴──────────────────│
│  Performance profile                       │
│  [ Turbo ] [ Balanced ] [ Lite ] [CPU][Off]│
│  Switching profiles reloads the model —    │
│  it takes a few seconds. "Off" frees all.  │
│                                            │
│  ⚠ Playing a game?  CPU-only is 4× faster  │
│    than Turbo while the GPU is busy.       │
│                                            │
│  Custom:  GPU layers ▓▓▓▓▓░░ 24/28         │
│           Context    [ 4096 ▾ ]            │
│           Threads    [ auto ▾ ]  [ Apply ] │
└────────────────────────────────────────────┘
```

### 5.2 Feature list — sidebar

- **New chat** (`Ctrl+Shift+O`) — a chat row is created only when you send the
  first message; its title becomes your first message, trimmed.
- **Live search** (`Ctrl+K`) across every stored conversation.
- **Delete** any chat; **rename** via the API.
- **Live memory meters** — VRAM and RAM bars for Anya herself, updating with the
  active profile.
- **🗂 Projects** — a second tab showing the current project, each project's task
  list and files, the activity log, and pending approvals (§5.10). From it you can
  **open a project's folder**, **delete** a project, or press **Keep working** to
  let her run unattended. The chat header has a matching **🗂 Projects** pill.

### 5.3 Chat area

- **Streaming replies** over Server-Sent Events — text appears as it is generated.
- **Markdown rendering** with fenced code blocks, language labels and a **Copy**
  button per block.
- **Stop button (■)** to abort a reply mid-flight.
- **Auto-title**, `Enter` to send, `Shift+Enter` for a newline.
- **Export** the conversation as Markdown.
- **Web step chips** — when browsing is on and a lookup runs, a small chip appears
  in the message (*"Searched the web — jetpack compose"*), and the reply ends with a
  **Sources** list (§5.9).
- A short **empty-state** with example prompts instead of a blank page.

### 5.4 The Power / Settings panel

A slide-in panel with two tabs:

- **Power** — the profile picker, the custom sliders, and the memory readout.
  (§6)
- **Settings** — a section-nav strip with a section per concern: system prompt
  (persona), creativity (temperature), auto-unload, backend choice, **Web
  browsing**, **Projects**, **Phone access**, **Updates**, and appearance.

All of it persists to a `config.json` and survives restarts. Every section is
independently collapsible and the whole panel scrolls, so it stays usable in a
short window.

### 5.5 The one thing that does not work: tool calling

If the model is sent an OpenAI-style `tools` array (which IDE "Agent Mode" does),
she does **not** call a tool. She prints the call as text and stops:

```
<code>{"name": "get_files", "arguments": {"path": "/my/project/path"}}</code>
```

…with no real tool call attached, and an invented path. Tool use is a *trained*
skill; a chat/code fine-tune does not acquire it for free. So: use her in **chat**
panels (VS Code, Android Studio's AI Assistant), not in agent mode.

**The workaround that does work.** The app in §5 asks the model for a *small JSON
object* ("ask for a lookup") and performs the action itself. That turns out to be
the same idea as real tool-calling but with the model's unreliability moved out of
the critical path: the app decides *when* to look things up, and the model is only
ever asked to *read the results* (§5.9). The same protocol drives **Projects**
(§5.10) — but there the app performs *writes and builds*, so the model's
unreliability is fenced in by a sandbox and an allow-list rather than being relied
on.

### 5.6 Design tokens

The look is a dark "IDE" palette, defined as CSS custom properties in one `:root`
block — easy to re-theme by editing seven lines:

```css
--bg:#0b0c10   --panel:#12141b  --panel2:#171a23  --panel3:#1e2230
--border:#232733  --border2:#2d3342
--text:#e8eaf0  --muted:#8a92a6  --dim:#5f6779
--accent:#7c5cff  --accent2:#a78bfa   (violet)
--ok:#34d399   --warn:#fbbf24   --bad:#f87171
--radius:14px   --radius-sm:10px
--font: system-ui stack     --mono: Cascadia Code / JetBrains Mono
```

### 5.7 The app's HTTP API

The GUI is just a client of this API — you can drive Anya from your own scripts:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/status` | profile, VRAM/RAM, speed, running state |
| `POST` | `/api/profile` | `{"profile":"cpu"}` — switch power profile |
| `POST` | `/api/chat` | `{"session_id":…,"message":…}` — streams SSE |
| `GET` | `/api/sessions` | list chats (`?q=` to search) |
| `GET` | `/api/sessions/<id>` | one chat with all messages |
| `DELETE` | `/api/sessions/<id>` | delete a chat |
| `GET` | `/api/export/<id>` | the chat as Markdown |
| `POST` | `/api/settings` | system prompt, temperature, auto-unload, backend, web, projects |
| `GET` | `/api/projects` | list projects |
| `POST` | `/api/projects` | create one |
| `GET` | `/api/projects/<pid>` | one project (tasks, activity, last build) |
| `DELETE` | `/api/projects/<pid>` | delete |
| `GET` | `/api/projects/<pid>/file?path=…` | read a file |
| `POST` | `/api/projects/<pid>/task` | add or move a task |
| `POST` | `/api/projects/<pid>/current` | focus this project |
| `POST` | `/api/projects/<pid>/build` | assemble the APK (log streams) |
| `GET` | `/api/approvals` | writes waiting for the user's OK |
| `POST` | `/api/approvals/<id>` | `{"approve":true|false}` |
| `GET` | `/api/health` | liveness + version (never requires the key) |
| `GET` | `/api/remote` | phone-access state: URLs, QR payload, tunnel status |
| `POST` | `/api/remote` | `{"enabled":…,"tunnel":…,"token":"…"}` or `{"new_token":true}` |
| `GET` | `/api/remote/qr.png` | the QR code as a PNG (generated locally) |
| `POST` | `/api/remote/tunnel` | `{"action":"install"|"start"|"stop"}` (Cloudflare quick tunnel) |
| `GET` | `/api/update` | latest GitHub release vs `VERSION` |
| `POST` | `/api/update/apply` | apply git-pull or zip-overlay, protecting user data |
| `POST` | `/api/restart` | restart the server to pick up new files |

`/api/status` also reports `web_enabled`, `web_max_pages`, `web_chars`, and a
`projects` block (root, focused project, list, tasks, last build, activity feed,
pending approvals). `/api/chat` streams SSE events of type `start`, `token`,
`tool`, `done`, `error`; the `tool` event carries the step chips the UI shows —
web lookups and project work alike.

```powershell
# Drop her to CPU-only before launching a game
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8091/api/profile `
  -ContentType application/json -Body '{"profile":"cpu"}'
```

### 5.8 History storage

SQLite (`anya_chats.db`), two tables, WAL mode:

```sql
sessions(id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL)
messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
         content TEXT, created REAL, tokens INTEGER, tps REAL, profile TEXT)
```

Storing `tokens` and `tps` **per message** is deliberate: it is what lets the UI
show honest speed figures and attribute them to the profile that produced them.
Backing up the entire history is one file copy.

### 5.9 Web browsing (optional, off by default)

A switch in the header (**🌐 Web**) plus three settings (on/off, lookups per reply,
text kept per page). Off, she is exactly the offline assistant described above and
says so. On, she can search and read pages. The implementation is one stdlib-only
module, `anya-ui/web.py` — no API keys, no libraries, no accounts.

**Why the app does the deciding.** A 1.5B model cannot be trusted to *choose* to
look something up. Asked "what's the newest version of Android Studio?", she
answers from stale weights and invents a version and a URL, confidently. So the
model is never the decision-maker:

| Path | Trigger | Model involved? |
|---|---|---|
| Open a page | the message contains a URL | no |
| Search | "search the web for X", "look up X", **or** a question about something that changes ("newest version of X", "how much does X cost", "the weather") | no |
| Ask for a lookup | she replies with `{"name":"web_search","arguments":{"query":…}}` | yes (best-effort) |

The first two are deterministic and reliable; the third is a bonus. `web.py` owns
the triggers (`wants_search`, `search_query_from`, `find_urls`) and the tolerant
tool-call parser (`parse_tool_call`), so all of it is testable without a model.

**Hiding the plumbing.** She was never trained to emit tool calls, so when she
replies with one the user must never see it. A small streaming filter
(`_ReplyFilter`) watches the tokens: a JSON object naming a tool is swallowed —
along with any code fence around it — while all ordinary text streams through
untouched. Prose *before* the object, a fenced object, or the object alone all
work; a JSON object that names no tool is shown as written; and an unfinished tool
call at the end of a stream is dropped. The user only ever sees step chips and a
normal answer, and the saved history is exactly what was shown.

**Grounding.** Fetched text is injected as a *user* message with explicit "use only
what this says, do not invent anything" wording, and each reply ends with a
**Sources** list (appended by the app if she forgot). Sources are real; her reading
of them is still written by a 1.5B model, so the Sources list is the trustworthy
part.

**Safety.** Public `http`/`https` only — `localhost`, private/link-local addresses
and `file://` are refused before any request. Pages are capped by bytes (400 KB)
and time (20 s), reduced to plain text, and truncated to the `web_chars` setting,
because *Balanced* is only a 4 096-token context. Repeated lookups in one turn are
cached and failures are remembered, so a URL can never be fetched three times.

**The trap worth knowing.** Several large sites (the developer.android.com family)
redirect to themselves and only then serve the page — a plain `urllib` request gets
a redirect loop. A shared cookie-aware `OpenerDirector` fixes it, which is why
`web.py` centralises all fetching through one opener.

### 5.10 Projects — real files and real APKs, in a sandbox

Web browsing lets Anya *read* the world; Projects lets her *write* to it. A
**🗂 Projects** tab (and a *Projects* switch in Settings) lets her create a
project, write and read files, keep a task list, and **assemble an installable
Android APK** — while proving that a fine-tune too small to be trusted with a
shell can still be *useful*, if the app holds the pen.

The design is deliberately the same shape as the web module: one stdlib-only file
(`projects.py`), pure trigger functions and a tolerant JSON tool parser, and all
real capability on the app's side of the line.

**What the app decides vs. what the model decides**

| Thing | Decided by |
|---|---|
| "This message wants a project made" (`projects.new_project_name`) | the app — regex |
| "This message wants a build" (`projects.wants_build`) | the app — regex |
| Creating the project, writing files, building | the app performs; the model only *requests* |
| Naming, code content, what to change | the model (`write_file` / `project_task` JSON) |

So *"make me an app called X and build it"* is deterministic end to end: the app
scaffolds a **working** Android Studio project and runs Gradle itself, which is why
a 1.5B model that writes non-compiling Kotlin can still produce a usable APK. Her
edits are a bonus layered on top; the pristine build always works.

**The sandbox is the safety argument.** Everything lives under one root
(`S:\anya-projects`), and `projects.py` — not the prompt — enforces:

- **No escape.** `..` in any path is refused. A relative path that resolves
  outside, or an absolute path outside the workspace, is not silently blocked —
  it becomes a **pending approval** in the tab, and nothing is written until the
  user accepts.
- **No shell.** Commands come from an allow-list (`gradlew, gradle, java, javac,
  kotlinc, python, git, adb, aapt2, apksigner, zipalign, d8, keytool`) executed as
  an argv, and the input is rejected outright if it contains a metacharacter
  (`; | & > < ^ \` $ \0`) or a destructive verb (`rm/del/rd/format`).
- **No surprise paths.** Builds use the Android Studio JBR and SDK already found
  on the machine; the model is steered to a single `build_apk` call instead of
  hand-run Gradle.
- **Bounded everything.** 2 MB per write, 40 k chars per read, 400 entries per
  list, 200 activity entries, 600 s per command, 1 800 s per build.

**What "what is she working on" actually is.** A `current.txt` holds the focused
project, so the tab survives restarts. Each project is a folder with a
`project.json` manifest: a task list (`todo → doing → done`), an append-only
activity log (`_log`), and the last build result. `/api/status` carries a compact
`projects` block, so the tab updates on the same 5-second poll as the VRAM meters —
there is no separate project UI to keep in sync.

**The honest caveat, same as the web.** A 1.5B model's `write_file` content is
often wrong (invented `R.layout.*`, a missing `package`, an import that does not
exist). The design absorbs that: the project always builds, and a failed build
hands the model the *tail of the real Gradle error* so she can try to fix it —
bounded by a one-tool-call-per-turn budget and a repeat-call guard.

**Unattended work.** A **Keep working** button turns that one-tool-per-turn loop
into a self-driving one: the app re-states the project's *real* state (tasks,
files, last build, her own previous step) to the model each turn and asks for the
next single action, feeding each result back in — so she keeps going without the
user supplying the next prompt. It stops on an explicit `{"name":"finish"}`, on a
step budget, or when the same step repeats (with one nudge first, because a small
model likes to circle). Every action still goes through the same sandbox, and the
stream is written to a log in the tab.

**Folder and delete.** Each project also has an **Open folder** button (opens the
sandbox folder in Explorer — the path is derived from the project id, so a request
can never point elsewhere) and a **Delete** button that removes the project and
all its files after a confirmation.

### 5.11 Phone access, mobile UI, and self-update (v0.17.0)

**Reaching her from a phone.** By default the app binds `127.0.0.1`, so only this
PC can reach it. The **Phone access** switch rebinds to `0.0.0.0` and mints a
shared **key**. Requests *from this machine* are always allowed; every other
client must present the key — as `?k=` in the link (which is then moved into a
cookie and stripped from the address bar), as a cookie, or as an `X-Anya-Key`
header. `/api/health` is deliberately exempt so a launcher can poll readiness
before unlocking. Rolling the key invalidates every paired phone.

Three routes out: **the same Wi-Fi** (just the LAN address), **Tailscale** (its
address is detected and offered when installed, so it works over mobile data with
no port-forwarding), and an optional **Cloudflare quick tunnel** (works from
anywhere with no account — the app downloads `cloudflared` on request and can
start/stop it), and the panel shows a **QR code** you scan with the phone.

That QR is the interesting part: rather than take a dependency, `qr.py` is a
complete, from-scratch encoder — byte mode, versions 1–40, L/M/Q/H error
correction, Reed–Solomon over GF(256), all eight masks with the standard penalty
scoring, and PNG output written through `zlib`. The success criterion is
**decodability**: it was validated against OpenCV across versions 1–18 and every
error level, and the live endpoint's PNG decodes to the exact LAN URL.

**A mobile UI, not a mobile app.** There is one page, and it reshapes. Under
860 px the sidebar becomes an off-canvas drawer (slid with `left` + `transition`,
with a tap-to-close scrim — deliberately not `transform`/`margin`, which behave
inconsistently in flex contexts), the top bar drops its text labels to icons so
nothing wraps, the settings panel goes full-width, and `100dvh` plus
`env(safe-area-inset-*)` keep the composer clear of the home bar. Inputs are 16 px
because iOS zooms the whole page on focus below that. Measured: no horizontal
overflow at 360 px or 390 px. All `localStorage` access goes through a wrapper, so
a browser that blocks storage degrades gracefully instead of failing to boot —
this was a real bug found by loading the page in a cross-origin iframe.

**Self-update.** A **Check for updates** button reads the newest release from
GitHub and compares it against `VERSION`. A `git`-cloned copy fast-forward pulls;
a ZIP download gets the release laid over the source. Either path is guarded by
explicit keep-lists (`config.json`, `anya_chats.db`, `approvals.json`,
`current.txt`, `models/`, `lora/`, `dataset/`, `logs/`, `tools/cloudflared/`), and
the guard was verified with a deliberately hostile release archive — **no user
data was touched**. She restarts herself when the files land.

---

## 6. The power limiter (the headline feature)

### 6.1 The problem

An 8 GB GPU running a game *and* an AI does not divide the memory — Windows pages
one of them in and out, and throughput collapses for both. So Anya's memory
footprint is a **runtime control**, not a startup flag.

### 6.2 Profiles

| Profile | GPU layers (`-ngl`) | Context | VRAM | RAM | When to use |
|---|---|---|---|---|---|
| **Turbo** | 28 / 28 | 8192 | ≈ 3.1 GB | ≈ 0.55 GB | GPU is free, want max speed |
| **Balanced** | 24 | 4096 | ≈ 2.7 GB | ≈ 0.93 GB | default |
| **Lite** | 8 | 4096 | ≈ 1.2 GB | ≈ 2.4 GB | leave some VRAM free |
| **CPU only** | 0 | 2048 | ≈ 0.08 GB | ≈ 3.0 GB | **gaming** — see below |
| **Off** | — | — | 0 | 0 | release everything |

Plus a **Custom** profile: GPU-layer slider (0–28), context (1024–16384) and CPU
thread count — all applied live.

### 6.3 Auto-unload

A watchdog can stop the model after *N* minutes of silence, so she never holds
memory while you are away. The next message reloads her automatically.

### 6.4 The counter-intuitive, measured result

With a game running, on this PC:

| Profile | Speed **while gaming** |
|---|---|
| **CPU only** | **11.1 tok/s** |
| Balanced | 2.9 tok/s |
| Turbo | 1.8 tok/s |

**CPU-only is ~4–6× faster than GPU when a game owns the card**, *and* it hands
the whole GPU back. GPU offload only wins when the GPU is free. Pressing **Off**
frees about 5.7 GB of RAM outright (15.1 GB → 9.4 GB in use).

### 6.5 How the footprint estimates are calibrated

Windows (WDDM) reports `[N/A]` for per-process VRAM, and `llama.cpp`'s memory
breakdown is not printed at default verbosity. So the app:

1. measures real anchors once — `ngl=0 → 80 MiB VRAM`, `ngl=8 → 1178`,
   `ngl=28 → 3043`, at 4096 context, with a 112 MiB KV cache;
2. **interpolates** between them for any layer count;
3. adds the KV cache, split in proportion to how many layers are on the GPU:

```
kv      = 112 MiB × (ctx / 4096)
vram    = interp(VRAM, ngl) + kv × (ngl / 28)
ram     = interp(RAM,  ngl) + kv × (1 − ngl / 28)
```

The UI labels these as estimates and replaces them with real numbers the moment a
profile is actually started. **Speeds are never claimed until measured** for that
profile — GPU/CPU speed swings by 5× depending on what else is running.

---

## 7. Architecture

```
        ┌──────────────────────────────────────────────┐
        │  Browser (app window)  ·  http://127.0.0.1:8091
        └───────────────────────┬──────────────────────┘
                                │  JSON + Server-Sent Events
        ┌───────────────────────▼──────────────────────┐
        │  anya_ui.py   (standard-library Python)      │
        │   • HTTP server      • SQLite chat history   │
        │   • power profiles   • idle watchdog         │
        │   • model supervisor ← starts / stops / swaps│
        │   • web.py (lookups) • projects.py (files,   │
        │        browse         tasks, APK builds) →   │
        └────────┬───────────────────────────┬─────────┘
                 │ spawns & supervises       │ or (settings)
        ┌────────▼────────────┐    ┌─────────▼──────────┐
        │ llama-server  :8090 │    │ Ollama   :11434    │
        │ (Vulkan, -ngl/-c)   │    │ model: anya        │
        └────────┬────────────┘    └─────────┬──────────┘
                 └───────────┬───────────────┘
                    ┌────────▼─────────┐
                    │ anya-f16.gguf    │  one file, 3.1 GB
                    └──────────────────┘
```

The **supervisor** is the key design choice: the app owns the model process, which
is what makes a real VRAM throttle possible. Switching profile = restarting
`llama-server` with different `-ngl`/`-c`/`--threads`. A "power off" (0 layers) is
just a profile with no process.

---

## 8. Traps and lessons (read this before building)

1. **Never blanket-kill `llama-server.exe`.** Ollama runs one of its own. Kill by
   matching the model file in the command line, or you will take down unrelated
   inference.
2. **Tool calling must be trained.** A chat fine-tune given a `tools` array will
   hallucinate a tool call as text. Either train tool use or use chat mode only.
3. **Attribute speed to the profile that produced it.** Capture tokens/sec during
   generation and store it; never read it at profile-switch time.
4. **Only display measured numbers.** Some profiles were never benchmarked; show
   nothing for those rather than a guess.
5. **Windows will not give you per-process VRAM.** Calibrate anchors and
   interpolate, and label the result an estimate.
6. **Reclaim the port before starting.** A previous server holds `:8090`; check and
   wait for it to free, or startup fails intermittently.
7. **Close leaked log handles.** If you redirect a child process's stdout/stderr
   to a file, close the handles after `Popen` — otherwise they leak.
8. **Context length is a hidden memory cost.** KV cache grows linearly with
   context; it is often what tips you over the edge, not the weights.
9. **Don't load two copies of the same model.** Pointing both an IDE plugin and
   the chat app at different ports quietly doubles RAM and VRAM usage.
10. **A shared single `.gguf`** keeps every consumer (Ollama, the app, an IDE)
    consistent and makes "two copies" easy to spot.

---

## 9. Adapting this to your own machine

### 9.1 Pick a base model by VRAM

| VRAM | Comfortable base model | Notes |
|---|---|---|
| 4 GB | 0.5–1.5B (F16) | fine for chat + small code |
| 6 GB | 1.5–3B (Q4) | |
| **8 GB** | **1.5B (F16) or 3–7B (Q4)** | Anya's tier |
| 12 GB | 7–8B (Q4/Q8) | |
| 16–24 GB | 8B (F16) or 13–14B (Q4) | noticeably better reasoning |

Train the **smallest model that meets your bar**, then spend your remaining
hardware budget on the memory throttle — that is what makes it usable *while you
do other things*.

### 9.2 Build checklist

1. Install a runtime (`Ollama`, and/or a `llama.cpp` build for the throttle).
2. Pick a base instruct model with a chat template.
3. Assemble a **mixed** dataset: identity + chat + domain + real code.
4. QLoRA fine-tune: 4-bit base, batch 1, gradient accumulation, gradient
   checkpointing, short sequence length.
5. Merge the adapter and convert to GGUF (`--outtype f16`).
6. Register it with your runtime and write your behaviour test battery.
7. Build the app: HTTP server + SQLite history + SSE streaming + a supervisor.
8. Add the **power profiles** and measure each one honestly.
9. *(optional)* Add web lookups — but do the *deciding* in the app, not the model
   (§5.9), and keep the fetch code in its own module so it can be tested alone.
10. *(optional)* Add **Projects** (§5.10): a sandboxed root, a JSON tool protocol,
    `write_file`/`build_apk` performed by the app, an approval queue for anything
    outside the root, and an allow-list for commands. Prove the build works
    *before* you let the model near it. Then add an **unattended loop**: re-state
    the project's real state each turn, ask for one action, feed the result back —
    with a step budget and a repeat guard so it can't cycle forever.
11. Re-run the behaviour test after *every* redeploy.

### 9.3 Making it yours

| To change… | Edit |
|---|---|
| Her name / personality | `identity.jsonl` **and** the system prompt (both) |
| What she is good at | the domain + repo-mined dataset chunks, then retrain |
| The look of the GUI | the `:root` CSS variables (§5.6) |
| The power tiers | the `PROFILES` table (layers / context / threads) |
| The runtime | the backend setting (`llama-server` ↔ `Ollama`) |

---

## 10. File map

```
Modelfile                  persona + chat template + sampling defaults
train\*.yaml               QLoRA training configuration
dataset\*.jsonl            training data (identity, chat, course, code…)
dataset\combine.py         merge + de-duplicate everything into all.jsonl
lora\                      the trained LoRA adapter (before merging)
models\anya-f16.gguf       the served model — one file, shared by every runtime

anya-ui\anya_ui.py         the app: HTTP server, history, profiles, supervisor
anya-ui\index.html         the whole interface (inline CSS/JS, no CDNs)
anya-ui\web.py             optional web browsing: search + page reading (stdlib)
anya-ui\projects.py        Projects: sandboxed files, tasks, commands, APK builds
anya-ui\voice.py           optional speech in/out (Whisper STT + Piper TTS, lazy)
anya-ui\memory.py          long-term memory: one JSON file, conservative extraction
anya-ui\learn.py           GitHub repo reader: recall + browsable library
anya-ui\qr.py              from-scratch QR encoder + PNG writer (no dependency)
anya-ui\remote.py          phone access: LAN/Tailscale addresses, tunnel launcher
anya-ui\updater.py         GitHub release check + safe git/zip update
anya-ui\start.ps1          desktop launcher (waits for readiness, then opens)
anya-ui\selftest.py        end-to-end test: chat, code, save, search, export, web
anya-ui\config.json        saved profile + settings + remote key + footprints
anya-ui\anya_chats.db      every conversation (SQLite)
anya-ui\current.txt        which project the Projects tab is focused on
anya-ui\approvals.json     writes waiting outside the workspace for your OK
S:\anya-projects\          the sandbox — every project, and `_template\android`
VERSION                    the version the GUI shows and the updater compares to

tools\redeploy_anya.ps1    merge → GGUF → register → restart
tools\anya-studio.ps1      check/prepare her for an IDE's local-model panel
tools\convert_hf_to_gguf.py  HF → GGUF converter (from llama.cpp)
GUIDE.md                   the full user manual
ANYA_OVERVIEW.md           this document
```

---

## Appendix — the commands

```powershell
# --- train -------------------------------------------------------------
llamafactory-cli train  .\train\qlora_qwen2.5-coder-1.5b.yaml
llamafactory-cli export .\train\export.yaml          # merge LoRA into the base
                                                     # (export_device: cpu, so it
                                                     #  doesn't fight for VRAM)

# --- to GGUF -----------------------------------------------------------
python S:\repos\llama.cpp-master\convert_hf_to_gguf.py `
       .\models\qwen2.5-coder-1.5b-merged --outtype f16 `
       --outfile .\models\anya-f16.gguf

# --- register with Ollama ---------------------------------------------
ollama create anya -f .\Modelfile

# --- run ---------------------------------------------------------------
ollama run anya                                      # quick terminal chat

# --- her app -----------------------------------------------------------
S:\envs\ai\Scripts\python.exe .\anya-ui\anya_ui.py   # GUI on :8091
S:\envs\ai\Scripts\python.exe .\anya-ui\selftest.py  # verify it still works

# --- drop her to CPU-only before a game --------------------------------
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8091/api/profile `
  -ContentType application/json -Body '{"profile":"cpu"}'
```

---

### Environment this was built and measured on

| | |
|---|---|
| CPU | Intel Core Ultra 5 225F (10c/10t) |
| GPU | NVIDIA RTX 5050, 8 GB, Blackwell (sm_120) |
| RAM | 16 GB DDR5-4800 |
| OS | Windows 11 Home |
| Python | 3.12 + PyTorch 2.11 (cu128) + LLaMA-Factory 0.9.5 |
| Runtime | Ollama + llama.cpp (Vulkan build) |

*Every performance and memory figure in this document was measured on this
machine. Numbers on other hardware will differ — in particular, CPU-only speed
depends heavily on your CPU's memory bandwidth.*
