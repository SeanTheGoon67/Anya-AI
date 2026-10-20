# Anya — local coding AI

Anya is a fine-tuned **Qwen2.5-Coder-1.5B** that runs entirely on this PC via
Ollama. Everything here builds, trains, exports and serves her. She is **offline by
default**; her own app has an optional **Web** switch that lets her search and read
pages, and a **Projects** tab where she writes real files and builds Android APKs
when you ask.

> **Want to just use her?** Double-click **`Anya`** on the desktop — her own chat
> window, with saved history and a memory limiter so you can game while she runs.
> Manual: **[GUIDE.md](GUIDE.md)** · app reference: **[anya-ui/README.md](anya-ui/README.md)** ·
> shareable blueprint: **[ANYA_OVERVIEW.md](ANYA_OVERVIEW.md)**.
>
> ```powershell
> ollama run anya          # or straight from a terminal
> ```

Goal: run a local coding assistant on this PC, and fine-tune our own version.

## Machine

| Part | Spec |
|---|---|
| CPU | Intel Core Ultra 5 225F (10c/10t) |
| GPU | NVIDIA RTX 5050, 8 GB VRAM, Blackwell (sm_120) |
| RAM | 16 GB DDR5-4800 (4 slots, max 128 GB) |
| OS | Windows 11 Home |
| Model store | `S:\ollama\models` |
| Python env | `S:\envs\ai` (Python 3.12 + PyTorch 2.11 cu128 + LLaMA-Factory 0.9.5) |
| HF cache | `S:\.cache\huggingface` |

## Status

- [x] Ollama 0.40.4 installed, models on `S:`
- [x] Baseline model pulled: `qwen2.5-coder:7b` (40 tok/s on this GPU)
- [x] Python 3.12 + venv at `S:\envs\ai`
- [x] PyTorch 2.11.0+cu128 — CUDA verified on RTX 5050
- [x] LLaMA-Factory 0.9.5 installed
- [x] VS Code installed
- [x] Dataset builders written + datasets generated (**22,442 examples**):
  - `identity.jsonl` — 49 identity examples (her name is **Anya**)
  - `chat.jsonl` — 4,000 conversation examples (Databricks Dolly 15k) — *chat ability*
  - `course.jsonl` — 145 hand-written Android/Kotlin/Compose/Python course Q&A — *explains concepts*
  - `teaching.jsonl` — 7,861 mined from real teaching repos + official Kotlin docs
  - `public.jsonl` — 1,200 general coding examples
  - `cocoon.jsonl` — 1,227 from inssekt/CocoonFE (platform schema)
  - `daijishou.jsonl` — 1,036 from TapiocaFox/Daijishou (platform schema)
  - `android_cannoli.jsonl` — 1,893 from CannoliHQ/cannoli (Kotlin + Compose app)
  - `android_mimir.jsonl` — 84 from jstamb/mimir (Kotlin, dual-screen)
  - `android_geemu.jsonl` — 94 from mertgoksumg/geemu (Kotlin + Compose)
  - `android_gobe.jsonl` — 201 from emilianorene/gobe (Kotlin + Compose for TV)
  - `cocoon_themes.jsonl` — 180 Cocoon `theme.json` authoring + field Q&A
  - `platform_launch.jsonl` — 58 launcher `platforms.json` records
  - `code_*.jsonl` — **~5,900** real Kotlin mined from 12 more repos
    (kotlinx.serialization, coil, detekt, ktor, iosched, tivi, kotlinx-datetime,
    kotlinx-atomicfu, mockk, accompanist, turbine, Pokedex)
  - `all.jsonl` — **22,442** combined, de-duplicated — *this is what v5 trained on*
- [x] QLoRA smoke test passed — 1.5B trains on 8 GB (loss 1.17 -> 0.76, 5 steps)
- [x] v1 fine-tune completed — 6,022 examples, 1,506 steps, **loss 0.382**, 1h00m
- [x] v2 fine-tune — chat + code balance (8,512 examples, 2,128 steps)
- [x] Merged LoRA + converted to GGUF (`models/anya-f16.gguf`, F16, 3.1 GB)
- [x] Loaded into Ollama as **`anya`** — ~84 tok/s on the RTX 5050
- [x] v3 fine-tune — chats + explains + codes (10,183 examples, 2,546 steps)
- [x] v4 fine-tune — 10,981 examples, 2,746 steps, **loss 0.395**, 1h00m
- [x] **v5 fine-tune (current)** — **22,442 examples** (double v4: +12 mined Kotlin repos,
      +3,000 chat, +8,000 teaching), 5,612 steps, 2 epochs, **2h59m**; merged → GGUF →
      reloaded into **both** Ollama and the browser UI (`VERSION` = **0.17.0**)
- [x] Persona: chats normally **and** writes code when asked (`Modelfile` SYSTEM + chat data)
- [ ] VS Code + Continue wired to local model
- [x] One-click launcher + full manual: `Start Anya.cmd`, `anya.ps1`, `GUIDE.md`
- [x] **Browser chat UI** — `Start Anya (browser).cmd` → <http://127.0.0.1:8090>
- [x] Behaviour test harness: `tools\test_anya.py` → `logs\anya_test.txt`
- [x] **v4 behaviour battery passed — 17/17 prompts** through Ollama
      (`logs\anya_test.txt`) and the browser server (`logs\anya_test_web.txt`); ~72-84 tok/s
- [x] Resumable training: `train\qlora_resume.yaml` + `tools\redeploy_anya.ps1`
- [x] **Anya's own app** — `anya-ui\` → desktop **`Anya`** icon, port 8091:
      stdlib-only Python server + hand-written UI, SQLite chat history with
      search/export/delete, streaming replies, and a **power/memory limiter**
      (`Turbo · Balanced · Lite · CPU only · Off` + GPU-layer slider, context,
      threads, auto-unload) that supervises `llama-server` itself. Measured on
      this PC: Turbo ≈ 3.1 GB VRAM, CPU-only ≈ 0.08 GB VRAM / 3.0 GB RAM.
      Self-test: `anya-ui\selftest.py` (all pass; `--web` adds the browsing checks).
- [x] **Web browsing** in her own app — a **🌐 Web** on/off switch, off by default
      (so she honestly says she's offline until you turn it on). Pasted links are
      read automatically, and explicit *"search the web for …"* requests — plus
      questions about things that change, like *"the newest version of X"* — are
      searched for her, because a 1.5B model won't reliably choose to. Replies end
      with a **Sources** list. Standard library only (`anya-ui\web.py`), public
      http/https only, per-page size/time caps. See `GUIDE.md` §11.
- [x] **Projects** — a **🗂 Projects** tab where she *makes* things, not just
      describes them: create a project, write/read real files, keep a task list
      with per-project history, and **build an installable Android APK**
      (`app-debug.apk`). Example prompt: *"Make me a small Android app called
      Dice Roller, then build the APK."* **Keep working** runs her unattended —
      she takes one step after another on her own (write, add a task, build)
      until she is done or you stop her; each project also has **Open folder**
      and **Delete** buttons. Standard library only
      (`anya-ui\projects.py`); the sandbox is **`S:\anya-projects`** and she can't
      write outside it — an outside path becomes an **approval** you see in the
      tab. Commands come from a fixed allow-list (`gradlew`, `java`, `kotlinc`,
      `git`, `adb`, …) with shell metacharacters refused. See `GUIDE.md` §12.
- [x] **Voice** — talk to her and let her read replies back: a **mic** button in
      the composer (whisper `small.en` for speech-to-text) and a **speaker**
      button (piper for speech-out). Both models load lazily and unload after
      **four minutes** idle, so they never hold VRAM while you game. The browser
      records 16 kHz mono WAV itself, so **no ffmpeg** is needed, and STT runs on
      the CPU by default. Standard library only (`anya-ui\voice.py`); switches and
      model pickers live in Settings. See `anya-ui\README.md`.
- [x] **Model switching (the "bigger model" option)** — the Power panel's
      **Model** section lists every `.gguf` in `S:\models` and reloads with the
      one you pick. Layer counts are read straight from each file's GGUF header,
      and the power profiles are stored as **fractions** of the layer count, so
      they retune themselves when you switch from the 1.5B to a 7B. A quantized
      `Qwen2.5-Coder-7B-Instruct Q4_K_M` (~4.4 GB, ~23 tok/s on this GPU at
      *Balanced*) is the drop-in "smarter" model.
- [x] **Long-term memory** — a **Memory** tab where Anya keeps a short list of
      durable facts about you and carries them into every chat. She learns in the
      background after each exchange; a **grounding filter** throws away anything
      a weak model invents (a fact survives only if the user's own words justify
      it), near-duplicate phrasings are merged, and you can add, delete or clear
      facts. Everything lives in one JSON file (`S:\anya-memory\memory.json`).
      Standard library only (`anya-ui\memory.py`).
- [x] **Themes** — a full-app recolouring system (14 built-in themes plus a custom
      accent), applied with CSS variables and persisted in `config.json` and
      `localStorage`, with an early inline script in `<head>` so the window never
      flashes the wrong colours while loading.
- [x] **Android Studio AI Assistant** wired to Anya through the built-in *Local
      Provider* (Settings → Tools → AI → Model Providers) on port **8090**, so
      only **one** copy of the model is loaded and her Power panel governs it.
      Chat works; **Agent Mode does not** (Anya has no tool-calling training — she
      prints a JSON tool stub as text). Helper: `tools\anya-studio.ps1`.
      See `GUIDE.md` §3b (setup) and §3c (`adb` / `git`).
- [x] **Phone access** — reach Anya from your phone on the same Wi-Fi (or from
      anywhere through an optional Cloudflare quick tunnel, no account needed).
      Turning it on binds her to your network and shows a **scannable QR code**
      plus the key she expects. The QR is generated by hand — a small
      dependency-free encoder (`anya-ui\qr.py`) — so nothing is phoned home.
      Requests from this PC are always allowed; a phone must present the key
      (via the link, which then sets a cookie). **Tailscale** addresses are
      detected and offered when you have it. See `GUIDE.md` §13.
- [x] **Auto-update button** — a **Check for updates** button in Settings reads the
      latest release from GitHub and offers **Update now** when there's a newer
      one. A copy cloned from GitHub fast-forward pulls; a plain download gets the
      release zip laid over the source — and **your `config.json`, chats, models,
      LoRA adapters, training data, library and saved items are never touched**
      (verified by a hostile-release test). She restarts herself when it's done.
- [x] **Mobile UI** — the whole app reshapes for a phone: the sidebar becomes a
      swipe-friendly drawer, the top bar drops its labels, the composer clears the
      home bar (`env(safe-area-inset-*)`), inputs sit at 16 px so iOS never zooms
      on focus, and there is no horizontal scroll at 360 px or 390 px. Storage
      access is wrapped, so a locked-down browser can't break the app.
- [x] **Dev tools on this PC** — `adb` added to the user `PATH`
      (`...\Android\Sdk\platform-tools`, v1.0.41) and **git 2.55.0** installed via
      `winget` (`C:\Program Files\Git`, on the system `PATH`). Neither is required
      by Anya; see `GUIDE.md` §3c.

## Data sources

| Repo | What it is | Training value |
|---|---|---|
| `iamtarun/python_code_instructions_18k_alpaca` | public coding instructions | general coding ability |
| `inssekt/CocoonFE` | Cocoon frontend — **platform config repo** | platform/emulator JSON schema |
| `TapiocaFox/Daijishou` | Daijishou frontend — **assets/config repo** | same schema family, more coverage |
| `CannoliHQ/cannoli` | open-source Kotlin + Jetpack Compose launcher | **real Android app architecture** |
| `jstamb/mimir` | open-source Kotlin dual-screen frontend | Android app code + dual-screen UI |
| `mertgoksumg/geemu` | open-source Kotlin + Compose frontend | Android app code |
| `emilianorene/gobe` | open-source Kotlin + Compose-for-TV frontend | Android app code |
| `databricks/databricks-dolly-15k` | human-written instruction/chat data (Apache-2.0) | **conversation ability** |
| `android/compose-samples` | official Jetpack Compose samples | Compose patterns + docs |
| `android/nowinandroid` | official modern Android app | architecture, best practices |
| `android/sunflower` | official Jetpack sample app | Compose + ViewModel |
| `android/architecture-samples` | official architecture samples | MVVM, repositories |
| `android/codelab-android-compose` | official Compose codelab | teaching exercises |
| `skydoves/android-developer-roadmap` | Android learning roadmap + docs | explanations |
| `Kotlin/kotlinx.coroutines` | coroutines library + guides | coroutine teaching |
| `Kotlin/kotlin-by-example` | Kotlin by Example | language teaching |
| `JetBrains/kotlin-web-site` | official Kotlin documentation (`docs/topics`) | **language course** |
| `JetBrains/kotlin-workshop` | JetBrains Kotlin workshop | language teaching |
| `philipplackner/CleanArchitectureNoteApp` | popular Android course author | clean architecture |
| `cocoon-shell.com/wiki` | Cocoon theme.json reference + feature docs | theme authoring, feature Q&A |
| `iisu-network/iiSU` | iiSU launcher — release/distribution repo only | almost none (no app code) |
| `magneticchen/Daijishou` | redirects to `TapiocaFox/Daijishou` (account gone) | — |
| `Daijishou/Daijishou-SDK` | Node.js SDK for extensions / DSESS scrapers | reference only (not yet in the set) |

### Key research finding

**Neither Cocoon nor Daijishou publishes its application source.**

- `inssekt/CocoonFE` and `TapiocaFox/Daijishou` are the **data/schema** layer
  (platform JSON + assets). The APKs are closed source (Releases only).
- `magneticchen/Daijishou` no longer exists — the repo moved to `TapiocaFox`.
- The closest **open-source** equivalents of Cocoon are Cannoli and Mimir, which
  is why their Kotlin source is now part of the training set.

Useful public references for building Cocoon-like features:
- <https://cocoon-shell.com/wiki/> — full feature list (Home grid, Widgets, Pods,
  Log, Picnic, Silk, Themes, Scraping, RetroAchievements, dual-screen).
- <https://cocoon-shell.com/wiki/theme-json-reference> — the theme format.
- `Daijishou/Daijishou-SDK` — the JS extension/scraper (DSESS) API.


## Limits (realistic)

- QLoRA fits at **1.5B–3B** comfortably; **7B is borderline** on 8 GB.
- 16 GB RAM and only ~4 GB free is the main constraint. 32 GB upgrade = best next spend.
- Fine-tuning shapes behavior/format/domain, it does not add new coding knowledge.

## Layout

```
README.md
dataset/build_dataset.py          # generic repo -> JSONL
dataset/build_kotlin_dataset.py   # Android/Kotlin/Compose -> JSONL
dataset/build_cocoon_dataset.py   # platform-schema JSON -> JSONL
dataset/build_cocoon_features.py  # Cocoon themes + platform launch configs
dataset/combine.py                # merge + de-duplicate all sources
dataset/*.jsonl                   # generated datasets
train/qlora_qwen2.5-coder-1.5b.yaml
lora/                             # trained adapters land here
anya-ui/anya_ui.py                # her app: HTTP server + history + model supervisor
anya-ui/index.html                # the interface (inline CSS/JS, no CDNs)
anya-ui/web.py                    # optional web browsing: search + page reading
anya-ui/projects.py               # Projects sandbox: files, tasks, commands, APKs
anya-ui/learn.py                  # GitHub repo reader + local code library (recall)
anya-ui/site_tools.py             # GitHub Pages site build/publish
anya-ui/voice.py                  # speech: whisper (STT) + piper (TTS), lazy-loaded
anya-ui/memory.py                 # long-term memory: facts, grounding filter, recall
anya-ui/start.ps1                 # desktop launcher (waits for readiness)
anya-ui/selftest.py               # end-to-end chat/history/export check (+ --web/--build/--voice)
tools/redeploy_anya.ps1           # merge LoRA -> GGUF -> Ollama + restart
tools/anya-studio.ps1             # check/prepare Anya for Android Studio's AI Assistant
env.ps1                           # activates the env with the right paths
```

## Quick start

```powershell
# activate env
. .\env.ps1

# build a dataset from a repo
python .\dataset\build_dataset.py --repo "C:\path\to\repo" --out .\dataset\mine.jsonl

# train
llamafactory-cli train .\train\qlora_qwen2.5-coder-1.5b.yaml
```

## Downloading a ready-to-run copy

The **source in this repository is complete on its own** — the app, the tool
modules and the docs. The *pre-trained weights* (the merged F16 GGUF, the LoRA
adapters and the exact Python environment) are far too large for a single GitHub
file, so they live on the **releases** page split into numbered parts: download
every part and extract them together into one folder.

## What the app does

Open **`Start Anya.cmd`** (or run `S:\envs\ai\Scripts\python.exe anya-ui\anya_ui.py`)
and you get one window on <http://127.0.0.1:8091> with:

- **Chat** — saved history, streaming replies, search, Markdown export.
- **Power limiter** — `Turbo · Balanced · Lite · CPU only · Off`, a GPU-layer
  slider, context size, threads and auto-unload, so she can run while you game.
- **Model** — pick any `.gguf` in the models folder; profiles retune to its size.
- **Web** — optional browsing, off by default.
- **Projects** — she writes real files and builds Android APKs in a sandbox.
- **Library** — read a GitHub repo, then recall its files in chat.
- **Memory** — durable facts about you, with a grounding filter.
- **Voice** — whisper in, piper out.
- **Site** — edit and publish a GitHub Pages site.
- **Themes** — 14 full-app colour schemes plus a custom accent.
