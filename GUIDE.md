# Anya — your local AI, and how to run it yourself

Anya is a **fine-tuned Qwen2.5-Coder-1.5B** model. It runs **100% on this PC**
through [Ollama](https://ollama.com). No accounts, no cloud, nothing leaves the
machine — **unless** you switch on **Web** in her own app (§11), which lets her
search and read pages when you ask her to, or let her work in **Projects** (§12),
where she writes real files into `S:\anya-projects` and builds Android APKs.

- **Model name in Ollama:** `anya`
- **Model weights:** `S:\ollama\models` (the `C:` drive is kept free)
- **What it is good at:** Python, Kotlin / Jetpack Compose (Android), emulator
  front-end config (platform JSON), and Cocoon-style `theme.json` files.
- **Personality:** she is a **normal chatbot _and_ a coder** — talk to her
  casually and she talks back; ask for code and she writes it. She knows her
  own name is **Anya**.

---

## 0. The quickest way to open it

Double-click **`Anya`** on your **desktop** — the icon with her portrait.

That opens **Anya's own chat window**:

- a clean chat interface, with a **sidebar of every past conversation** you can
  browse, search, reopen and export
- replies stream in as she writes them; code arrives in copyable fenced blocks
- a **Power panel** (top-right) that trades speed for memory —
  *Turbo · Balanced · Lite · CPU only · Off*, plus a fine GPU-layer slider,
  context size and CPU-thread count — so you can **leave her running while you
  play a game**

The launcher waits until the app is actually answering before it opens the
window, so you will **never** see *"server unavailable"*. The second click is
instant (it reuses the running app).

> **Playing a game?** Pick **CPU only** in the Power panel — measured on this PC
> it is ~4× faster than the GPU modes while a game is running, because the game
> and Anya fight over the same 8 GB of VRAM. Or press **Off** to free the card
> entirely. See **§10**.

Full details, the API and troubleshooting live in **`anya-ui\README.md`**.

> The old `llama-ui.lnk` (a bare Brave web link — the original cause of *server
> unavailable*) is no longer needed. `Start Anya.cmd` still works if you prefer a
> terminal.

---

## 1. The five ways to use Anya

### A. Her own app (easiest)
Double-click **`Anya`** on the desktop — see **§10**.

### B. One click in a terminal
Double-click `Start Anya.cmd`, then just type to her. `/bye` leaves.

### C. From any PowerShell window
```powershell
ollama run anya
```
If it says *"could not connect to ollama app"*, the background server isn't
running. Start it once (it keeps running afterwards):
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```
…then in a **new** window run `ollama run anya` again.
Or just use `.\anya.ps1`, which does the check for you.

### D. Inside VS Code (like Copilot)
See section 3.

### E. Inside Android Studio (built-in AI Assistant)
See section 3b. (`adb` and `git` are covered in section 3c.)

### F. In the raw llama.cpp page
Double-click **`Start Anya (browser).cmd`** (or run `.\anya-web.ps1`).

It starts `llama-server` with the Anya GGUF and opens **<http://127.0.0.1:8090>** —
the bare llama.cpp chat page. This is the page **§10's app replaces**; it is
still handy when you just want the raw server. Type in the box at the bottom and
press Enter.

> Note: if Anya's app (§10) is already running, it owns that server — pressing
> *Off* there stops it. Use the app unless you have a reason not to.

- The page has settings (gear icon) where you can set a **system prompt**. Paste
  this so she always chats naturally *and* codes on request:
  `You are Anya, a friendly assistant that runs entirely offline on this PC. Your name is Anya. Chat normally, and write code in fenced blocks when asked.`

> This prompt says she is offline — and on this route she *is*. Web browsing
> (§11) only exists inside her own app, which adds its own instruction when you
> switch **Web** on.

> **Chat or code?** She does both. Just talking to her gets a normal,
> conversational answer; asking for code gets code in a fenced block. If you
> want *only* raw code, say so ("code only, no explanation").
- Server logs: `S:\tools\logs\llama-server.err.log`
- To stop the model, use Anya's app (**§10**) or switch its profile to *Off* —
  do **not** run `Get-Process llama-server | Stop-Process`, which would also kill
  the server Ollama uses for Android Studio.

---

## 2. Terminal cheat-sheet

| What you want | Command |
|---|---|
| Chat with Anya | `ollama run anya` |
| Leave a chat | `/bye` |
| List installed models | `ollama list` |
| Show what's loaded in memory | `ollama ps` |
| Show Anya's settings/template | `ollama show anya` |
| Unload Anya from VRAM (frees the GPU) | `ollama stop anya` |
| Delete Anya | `ollama rm anya` |
| Re-create Anya after retraining | `ollama create anya -f Modelfile` |
| Is the server up? | open <http://127.0.0.1:11434> in a browser |

Inside a chat you can also use:
`/set parameter temperature 0.1`   …lower randomness
`/set parameter num_ctx 8192`      …longer context (uses more VRAM)
`/clear`                            …reset the conversation
`/?`                                …help

---

## 3. VS Code + Continue (chat inside your editor)

One-time setup:

1. Install the extension:
   ```powershell
   code --install-extension Continue.continue
   ```
2. Copy the prepared config:
   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.continue" | Out-Null
   Copy-Item "C:\Users\Administrator\Documents\Default Project\vscode\continue-config.json" `
             "$env:USERPROFILE\.continue\config.json" -Force
   ```
3. (Optional, for "index my codebase" features) pull an embeddings model:
   ```powershell
   ollama pull nomic-embed-text
   ```
4. Restart VS Code. Open the **Continue** panel (the icon in the left sidebar)
   and pick **"Anya 1.5B (fine-tuned, local)"** from the model dropdown.

You can now highlight code → **Ctrl+I** / right-click → *Add to Continue* to ask
Anya about it.

> Autocomplete uses the bigger `qwen2.5-coder:7b` because it is noticeably better
> at inline completion. Anya is the "chat/assistant" model.

---

## 3b. Inside Android Studio (the built-in AI Assistant)

Android Studio here is **2026.1.4**, which can talk to a local model directly —
no plugin and no cloud account. It does not do everything Gemini does, but the
**chat window** works. (Do **not** install Continue's JetBrains plugin for this;
the built-in model provider is cleaner and is what this section sets up.)

**Step 1 — make sure she is running.** Open her from the desktop icon (§0), or
run the readiness helper, which checks both endpoints, offers to start her, and
prints the exact values to type:

```powershell
cd "C:\Users\Administrator\Documents\Default Project"
.\tools\anya-studio.ps1 -NoChat      # add -Start to launch her app if it's down
```

**Step 2 — inside Android Studio** (`C:\Program Files\Android\Android Studio\bin\studio64.exe`):

1. `File → Settings → Tools → AI → Model Providers`
2. Click the **+** (add) icon → **Local Provider**
3. Enter a description of the model provider — call it **`Anya (local)`**
4. **Set the port** the provider is listening on — **`8090`** (see below)
5. **Enable a model** — tick the entry the wizard lists
6. Open the **Gemini chat** window and use the **model picker** to switch from
   the default Gemini model to your local Anya

### Which port — 8090 or 11434?

Anya can be reached on two ports. Prefer the first:

| Port | What it is | When to use it |
|---|---|---|
| **8090** | Anya's own app (`anya-ui`). **One** copy of the model, and her **Power** panel decides how much VRAM/RAM she may use. | Normal choice. |
| 11434 | Ollama (`anya`). Autostarts with Windows, so it is always available. | Fallback if 8090 is not discovered — but it loads a **second** copy of the model if her app is also running, which hurts on 16 GB RAM during gaming. |

Run `tools\anya-studio.ps1` at any time: it lists which ports are live and which
model each one exposes.

### What works, and what does not

| Feature | Verdict |
|---|---|
| **Chat** window | **Works.** Talk to her, paste code, get Kotlin back. |
| **Agent Mode** | **Does not work.** |

Agent Mode drives the IDE by handing the model a list of *tools* (read file, edit
file, run a build…). Anya was never trained on tool calling, so instead of calling
a tool she **prints the call as plain text** and stops:

> Ask: *"Which files are in my project?"* (sent with a `tools` array)
> She answers: `<code>{"name": "get_files", "arguments": {"path": "/my/project/path"}}</code>`
> — as ordinary text, with no real tool call attached, and an invented path.

Google's own documentation says the same thing: some IDE AI features "are
nonfunctional with a local model", while "the AI chat feature … is generally
supported".

**So: chat only.** If you want an *offline agent* in the IDE, point the local
provider at the larger `qwen2.5-coder:7b` (already installed) — it handles tools
much better. Anya stays the chat/companion model. For full agentic work, use the
cloud Gemini model.

---

## 3c. Do I need `adb` and `git`?

Short answer: **neither is needed** — not for Anya, and not for the Android Studio
wiring above. They are two independent conveniences — and both are **now installed**
on this PC. Here is exactly what each one is and what it buys you.

### `adb` — Android Debug Bridge

`adb` is the command-line tool that talks to Android phones and emulators. It is
already on this PC, inside the SDK:

```
C:\Users\Administrator\AppData\Local\Android\Sdk\platform-tools\adb.exe
```

Android Studio uses it internally, and that already works. It is **also on your
`PATH` now** (added to your user `PATH`), so `adb` works in any *new* terminal:

| Command | What it does |
|---|---|
| `adb devices` | list the phones/emulators Android Studio can see |
| `adb install app.apk` | install a build straight to a connected phone |
| `adb logcat` | stream the device's logs — invaluable when an app crashes on launch |
| `adb shell` | get a command prompt *on* the phone |
| `adb push` / `adb pull` | copy files to/from the device |

**Done.** Open a *new* terminal (existing ones keep the old `PATH`) and `adb
devices` works.

### `git` — version control

`git` is **now installed** — 2.55.0, via `winget`, in `C:\Program Files\Git`, with
`C:\Program Files\Git\cmd` on the system `PATH`.

- **Anya does not need it.** Her training repos were downloaded as ZIP archives
  (§6/§7) and everything in this project is plain files — no repository.
- **Android Studio's Git features now work.** Restart Studio once; its *Version
  Control* panel / *Git* tool window will find git by itself.
- In a terminal, `git --version` works in any *new* window (existing ones keep the
  old `PATH`).

Two things to know before your first commit: git wants an identity, so set it once
(with your own details):

```powershell
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

Nothing in this project depends on git — it is purely for your own code.

> Neither of these touches Anya's model, her app, or the Studio chat integration —
> they are purely about how you work with the code around her.

---

## 4. Use Anya from your own code (HTTP API)

Ollama exposes a local REST API on `http://127.0.0.1:11434`.

**PowerShell / curl:**
```powershell
curl http://127.0.0.1:11434/api/generate -d '{\"model\":\"anya\",\"prompt\":\"What is your name?\",\"stream\":false}'
```

**Python:**
```python
import requests

r = requests.post("http://127.0.0.1:11434/api/chat", json={
    "model": "anya",
    "messages": [
        {"role": "system", "content": "You are Anya, a local coding assistant."},
        {"role": "user",   "content": "Write a Kotlin data class for a game."},
    ],
    "stream": False,
})
print(r.json()["message"]["content"])
```

---

## 5. Where everything lives

| Thing | Path |
|---|---|
| **Anya model** (Ollama) | `S:\ollama\models` |
| Ollama program | `C:\Users\Administrator\AppData\Local\Programs\Ollama\ollama.exe` |
| **This project** | `C:\Users\Administrator\Documents\Default Project` |
| Python environment | `S:\envs\ai` |
| Hugging Face cache | `S:\.cache\huggingface` |
| Downloaded source repos | `S:\repos` |
| **Teaching repos** (Android/Kotlin) | `S:\repos-teach` |
| Downloaded llama.cpp (GGUF converter) | `S:\repos\llama.cpp-master` |
| llama-server (browser UI) | `S:\tools\llama-vulkan` |
| Merged HF model (pre-Ollama) | `models\qwen2.5-coder-1.5b-merged` |
| LoRA adapter | `lora\qwen2.5-coder-1.5b-lora` |
| Training config | `train\qlora_qwen2.5-coder-1.5b.yaml` |
| Training log | `logs\train_v4.log` (latest) |
| Anya behaviour test | `tools\test_anya.py` → `logs\anya_test.txt` |
| **Cheat-sheet for you** | `GUIDE.md` (this file) |
| **Anya's app (chat window)** | `anya-ui\` → `anya-ui\README.md` |
| App launcher (desktop icon) | `anya-ui\start.ps1` |
| Studio readiness helper | `tools\anya-studio.ps1` |
| Saved conversations | `anya-ui\anya_chats.db` |
| App settings | `anya-ui\config.json` |
| One-click launcher (terminal) | `Start Anya.cmd` / `anya.ps1` |
| Raw llama.cpp page launcher | `Start Anya (browser).cmd` / `anya-web.ps1` |
| Anya's app self-test | `anya-ui\selftest.py` |

---

## 6. Rebuild Anya from scratch (the full pipeline)

Everything below assumes:
```powershell
cd "C:\Users\Administrator\Documents\Default Project"
. .\env.ps1          # activates S:\envs\ai and sets the cache paths
```

**1. Build / refresh the datasets**
```powershell
# --- who she is, how she talks, and what she knows about coding --------------
python .\dataset\build_identity.py       --out .\dataset\identity.jsonl
python .\dataset\build_chat_dataset.py   --out .\dataset\chat.jsonl --total 4000
python .\dataset\build_course_dataset.py --out .\dataset\course.jsonl

# --- teaching material mined from real Android/Kotlin repos ------------------
# one-time: download the teaching repos (no git needed)
powershell -ExecutionPolicy Bypass -File .\tools\fetch_teaching_repos.ps1
powershell -ExecutionPolicy Bypass -File .\tools\fetch_more_repos.ps1   # second wave
# plus the official Kotlin language docs (~120 files, only a few MB)
powershell -ExecutionPolicy Bypass -File .\tools\fetch_kotlin_docs.ps1
python .\dataset\build_teaching_dataset.py --root S:\repos-teach --out .\dataset\teaching.jsonl `
  --max-md 9000 --max-kdoc 6000 --per-file 20

# --- domain + code data from the emulator-front-end repos on S:\repos --------
python .\dataset\build_cocoon_features.py
python .\dataset\build_cocoon_dataset.py --repo S:\repos\CocoonFE-main    --out .\dataset\cocoon.jsonl
python .\dataset\build_cocoon_dataset.py --repo S:\repos\Daijishou        --out .\dataset\daijishou.jsonl
python .\dataset\build_kotlin_dataset.py --repo S:\repos\cannoli-main     --out .\dataset\android_cannoli.jsonl
python .\dataset\build_kotlin_dataset.py --repo S:\repos\mimir-main       --out .\dataset\android_mimir.jsonl
python .\dataset\build_kotlin_dataset.py --repo S:\repos\geemu-main       --out .\dataset\android_geemu.jsonl
python .\dataset\build_kotlin_dataset.py --repo S:\repos\gobe-main        --out .\dataset\android_gobe.jsonl

# --- extra real Kotlin code mined from the second-wave repos -----------------
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\kotlinx.serialization-master --out .\dataset\code_serialization.jsonl --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\coil-main                     --out .\dataset\code_coil.jsonl          --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\detekt-main                   --out .\dataset\code_detekt.jsonl        --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\ktor-main                     --out .\dataset\code_ktor.jsonl          --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\iosched-main                  --out .\dataset\code_iosched.jsonl       --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\tivi-main                     --out .\dataset\code_tivi.jsonl          --max-examples 800 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\kotlinx-datetime-master       --out .\dataset\code_datetime.jsonl      --max-examples 300 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\kotlinx-atomicfu-master       --out .\dataset\code_atomicfu.jsonl      --max-examples 300 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\mockk-master                  --out .\dataset\code_mockk.jsonl         --max-examples 300 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\accompanist-main              --out .\dataset\code_accompanist.jsonl   --max-examples 300 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\turbine-trunk                 --out .\dataset\code_turbine.jsonl       --max-examples 300 --per-file 30
python .\dataset\build_kotlin_dataset.py --repo S:\repos-teach\Pokedex-main                  --out .\dataset\code_pokedex.jsonl       --max-examples 300 --per-file 30

# --- merge everything into one de-duplicated set -----------------------------
python .\dataset\combine.py --out .\dataset\all.jsonl `
  identity.jsonl chat.jsonl course.jsonl teaching.jsonl public.jsonl `
  cocoon.jsonl daijishou.jsonl `
  android_cannoli.jsonl android_mimir.jsonl android_geemu.jsonl android_gobe.jsonl `
  cocoon_themes.jsonl platform_launch.jsonl `
  code_serialization.jsonl code_coil.jsonl code_detekt.jsonl code_ktor.jsonl `
  code_iosched.jsonl code_tivi.jsonl code_datetime.jsonl code_atomicfu.jsonl `
  code_mockk.jsonl code_accompanist.jsonl code_turbine.jsonl code_pokedex.jsonl
```

**2. Train the LoRA adapter** (~3 h on the RTX 5050 for ~5,600 steps / 2 epochs,
22,442 examples — see `train\qlora_qwen2.5-coder-1.5b.yaml`)
```powershell
llamafactory-cli train .\train\qlora_qwen2.5-coder-1.5b.yaml
```

**3. Merge the adapter into a full model**
```powershell
llamafactory-cli export .\train\export.yaml
```

**4. Convert to GGUF**

> Ollama's safetensors importer does **not** support Qwen2 ("unsupported MLX
> architecture"), so we convert to GGUF first with llama.cpp's converter.
> (One-time: download <https://github.com/ggml-org/llama.cpp> to `S:\repos\llama.cpp-master`
> and `pip install gguf sentencepiece`.)

```powershell
python S:\repos\llama.cpp-master\convert_hf_to_gguf.py `
  .\models\qwen2.5-coder-1.5b-merged `
  --outfile .\models\anya-f16.gguf --outtype f16
```

**5. Import into Ollama as `anya`**
```powershell
ollama create anya -f .\Modelfile   # Modelfile FROMs .\models\anya-f16.gguf
ollama run anya
```

> **Shortcut:** steps 2-5 are wrapped up in
> `powershell -ExecutionPolicy Bypass -File .\tools\redeploy_anya.ps1`
> (merge → GGUF → `ollama create` → restart the browser UI).
>
> **If training is interrupted** (power cut, restart, crash) you do **not** start
> over. `lora\qwen2.5-coder-1.5b-lora\checkpoint-*` holds the last saved state.
> Set `resume_from_checkpoint:` in `train\qlora_resume.yaml` to that folder and:
> ```powershell
> llamafactory-cli train .\train\qlora_resume.yaml
> ```
> It continues from the saved step instead of epoch 0.

That's the whole loop. To tweak the personality, edit the `SYSTEM """..."""`
line in `Modelfile`, re-run `ollama create anya -f .\Modelfile`, and you're done
(no retraining needed for prompt-level changes).

---

## 7. Adding more repos to the training set

Anything on GitHub can be pulled without `git`:
```powershell
# whole repo (small ones)
Invoke-WebRequest "https://codeload.github.com/OWNER/REPO/zip/refs/heads/main" -OutFile S:\repos\_zips\repo.zip
Expand-Archive S:\repos\_zips\repo.zip -DestinationPath S:\repos

# then turn it into data
python .\dataset\build_kotlin_dataset.py --repo S:\repos\REPO-main --out .\dataset\android_extra.jsonl
# and add android_extra.jsonl to the combine.py line above
```

`tools\fetch_repo_paths.ps1` downloads **only selected folders** of a repo —
handy for huge repos full of images (that's how Daijishou's 7 GB of assets was
avoided).

---

## 8. Troubleshooting

**"could not connect to ollama app"**
The server isn't running. Start it:
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

**"model 'anya' not found" but `ollama list` is empty**
Ollama can't see the models on `S:`. Make sure the user variable is set, then
open a **new** terminal:
```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS','S:\ollama\models','User')
```

**Everything is slow / the whole PC stutters**
Anya stays in VRAM for 5 minutes after last use. Free it with `ollama stop anya`.
Also close games/browsers — 8 GB of VRAM is shared.

**Out-of-memory during training**
Lower `cutoff_len` in `train\qlora_qwen2.5-coder-1.5b.yaml` (e.g. 512 → 384) or
keep `num_train_epochs: 2`.

**Anya "forgot" her name**
She should always answer as Anya thanks to the `SYSTEM` prompt in `Modelfile`.
If you use a client that ignores system prompts, re-apply:
```powershell
ollama create anya -f .\Modelfile
```

**Anya replies with `{"name": "get_info", "arguments": {}}` instead of an answer**
Something is sending *tool definitions* to her along with the message (a
client's agent mode, or a "tools" parameter in a script). Anya is not trained
for function calling, so she answers with a tool-call stub — and the tool name
she echoes is whatever the client offered, not something she invented.

Verified on this PC: the same question goes through `{"name":"get_info"}` → JSON
output, and with no tools → a normal chat answer.

Fix: turn off agent/tool mode in the client, or in your own code just don't send
`tools`:
```powershell
curl http://127.0.0.1:11434/api/chat -d '{\"model\":\"anya\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false}'
```

**I want a clean slate**
```powershell
ollama rm anya
ollama create anya -f .\Modelfile
```

---

## 9. Honest limits

- Anya is **1.5B parameters**. She is fast and knows this project's formats
  well, but a 7B/14B model will still out-code her on hard problems. For
  autocomplete you already have `qwen2.5-coder:7b` installed.
- Fine-tuning changes **style, format and domain focus**; it does not add large
  amounts of new factual knowledge.
- The training repos are *open-source emulator front-ends* (Cannoli, Mimir,
  Geemu, Gobe). Cocoon and Daijishou themselves are closed source, so Anya
  learned their **data formats** (platform JSON, theme.json), not their internals.
- 16 GB of RAM is the machine's tightest constraint. A 32 GB kit is the best
  next upgrade if you want to train bigger models. Anya's app (**§10**) can stop
  the model entirely (*Off*) or move it to the CPU, which is how you keep her
  around while gaming.
- With **Web on** (§11), the *links* she gives you are real — the app fetched
  them. Her *summary* of them is still written by a 1.5B model and can misread a
  version number or a date. Check the Sources.

---

## 10. Anya's own app

The desktop **`Anya`** icon opens her own window — a clean chat interface with
saved history and a memory limiter. This replaces the bare `llama-ui` page.

**What it gives you**

- **History.** Every conversation is saved in `anya-ui\anya_chats.db` (SQLite).
  The sidebar lists them newest-first; search with `Ctrl+K`; `×` deletes one;
  **Export** downloads the open chat as Markdown.
- **Streaming chat.** Replies appear as she writes. Code comes in fenced blocks
  with a **Copy** button. The ■ button stops a reply mid-sentence.
- **Power panel** (top-right button). Trades speed against memory and reloads the
  model on the spot:

  | Profile | GPU layers | Context | Anya's VRAM | Anya's RAM |
  |---|---|---|---|---|
  | **Turbo** | all 28 | 8 192 | ≈ 3.1 GB | ≈ 0.55 GB |
  | **Balanced** | 24 | 4 096 | ≈ 2.6 GB | ≈ 0.9 GB |
  | **Lite** | 8 | 4 096 | ≈ 1.2 GB | ≈ 2.4 GB |
  | **CPU only** | 0 | 2 048 | ≈ 0.08 GB | ≈ 3.0 GB |
  | **Off** | — | — | 0 | 0 |

  These are **measured on this PC**, and the panel refreshes them from
  llama.cpp's own memory report every time a profile starts. **Fine tune** adds a
  GPU-layer slider (0–28), context length (1 024–16 384) and CPU-thread count.
  **Auto-unload** stops the model after N idle minutes.
- **Settings tab.** System prompt, creativity (temperature), auto-unload, the
  backend (`llama-server` or `ollama`), **web browsing** (§11) and **Projects**
  (§12).

**The Projects tab (§12).** Next to chat history, the sidebar has a **🗂 Projects**
tab that shows what she is building — her current project, each project's task
list and files, a running history of every action, and any write waiting for your
approval.

**While gaming: pick CPU only.** This is measured, not a guess. On this 8 GB card
the game and Anya fight over the same VRAM, and Windows pages one of them in and
out:

| Profile | Speed *while a game is running* |
|---|---|
| **CPU only** | **11.1 tok/s** |
| Balanced | 2.9 tok/s |
| Turbo | 1.8 tok/s |

So the GPU modes are only faster **when the GPU is free**. With a game up, the
CPU profile is several times quicker *and* hands the whole card back. **Off**
frees the most (~3 GB VRAM and ~3 GB RAM).

**Under the hood**

- The app is `anya-ui\anya_ui.py` (standard-library Python only) and serves
  **<http://127.0.0.1:8091>**. It *supervises* `llama-server` itself — starting,
  stopping and restarting it — which is what makes real VRAM control possible.
  Ports: **8091** app, **8090** model, **11434** Ollama.
- It only ever kills processes whose command line contains `anya-f16.gguf`, so
  Ollama's own `llama-server` (used by Android Studio) is never touched.
- Launcher: `anya-ui\start.ps1` (waits for the app to answer, then opens a Brave
  app-window; instant on later clicks).
- Self-test: `S:\envs\ai\Scripts\python.exe anya-ui\selftest.py` — drives the real
  API (chat, history, search, export, delete) and prints PASS/FAIL for each.
  Add `--web` to include the browsing checks (§11), which need internet.

Full reference, the HTTP API and troubleshooting: **`anya-ui\README.md`**.

---

## 11. Giving Anya the web (optional)

By default Anya is exactly what she was before: **fully offline**, and she says so
if you ask. The **🌐 Web** button in the top-right of her window turns on the
other mode. It is a plain on/off switch — nothing happens on the network until you
turn it on, and turning it off puts her straight back to being offline.

**Why it is built the way it is.** Anya was never trained for real tool-calling,
and at 1.5B she cannot be trusted to *decide* to look something up: asked "what's
the newest version of Android Studio?", she will answer from stale memory and
invent a version number and a fake link, with total confidence. So the app does
two things:

1. **It looks things up for her when the message clearly calls for it.**
   - You paste a link → the page is read and handed to her.
   - You say *"search the web for …"* — or ask about something that obviously
     changes (*"the newest version of X"*, *"how much does X cost"*, *"the
     weather"*) — and the search is run before she is even asked.

   These two paths do not depend on the model co-operating, so they always work.
- She can **also** ask for a lookup herself, by replying with one small JSON
  object (`{"name": "web_search", "arguments": {"query": "…"}}`). The app
  notices, runs it, hides the plumbing, and hands her the results. It is a bonus
  path, not the one you rely on.

**How to turn it on**

1. Click **🌐 Web off** in the header (top-right, next to the power button). It
   turns green and reads **Web on**.
2. That's it. Ask her something current, or paste a link.

The **Settings** tab has the same switch plus:

| Setting | Default | Meaning |
|---|---|---|
| Web lookups per reply | 3 | how many searches/pages she may use in one answer |
| Text kept per page | 1 400 chars | how much of each page she gets to read |

**What she will and won't do**

- She searches **DuckDuckGo** (the HTML endpoint — no API key, no account) and
  reads pages with Python's standard library. Nothing extra to install.
- Every reply that used the web ends with a **Sources** list of the links. If she
  forgot to cite them, the app appends them, so the links are always in the saved
  history and in the Markdown export.
- **Sources are real; her reading of them is not always.** A 1.5B model will
  sometimes quote the wrong version number out of a correct page. Treat the
  **Sources** list as the trustworthy part and the prose as a summary.
- Links are restricted to **public http/https**. `localhost`, private network
  addresses and `file://` are refused, so a stray link cannot reach into this PC.
  Requests are capped by size (400 KB) and time (20 s) per page.
- **Context matters.** Web results go into her context window, and *Balanced* is
  only 4 096 tokens. For a lot of browsing use **Turbo** (8 192).

> Note: the *browsing* lives in her own app. The Ollama model (`ollama run anya`)
> and the Android Studio route have **no** web access, and in those she still says
> — correctly — that she is offline.

**Test it**

```powershell
# the browsing end-to-end (needs internet), then restores your setting
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py --web
```

The module behind it is `anya-ui\web.py`; you can try it on its own:

```powershell
S:\envs\ai\Scripts\python.exe -c "import sys; sys.path.insert(0,r'C:\Users\Administrator\Documents\Default Project\anya-ui'); import web; print(web.search('jetpack compose navigation')[:3])"
```

**Troubleshooting**

| Symptom | Cause / fix |
|---|---|
| She says she can't look things up | The **Web** switch is off — that is her honest answer. Turn it on. |
| "couldn't reach the site" | No internet, or the site is down. She reports this; she does not fake it. |
| "that address isn't reachable from the app" | You gave a `localhost`/private address, or a made-up domain. |
| "HTTP 403" from a site | The site blocks non-browser clients. Pick another source. |
| Search returns nothing | DuckDuckGo rate-limits bursts. Wait a moment and try again. |
| Results fill her context / she gets vague | Drop **Text kept per page**, or switch to **Turbo**. |

Full reference, the HTTP API and troubleshooting: **`anya-ui\README.md`**.

---

## 12. Projects — she builds the thing, not just describes it

Normally Anya *tells* you how to do something. With **Projects** she does it in a
real folder on this PC: she creates a project, writes and reads files, keeps a
task list, and **builds an Android APK** you can install on a phone.

### Where it clicks

In her window, in the **chat** — just ask:

> Make me a small Android app called Dice Roller, then build the APK.

She makes the project, and a minute later there is a working, auto-signed
`app-debug.apk`. Small chips appear in the reply as each step happens
(*"Created project — dice-roller"*, *"Building the APK"*), and the build log
streams into the **🗂 Projects** tab while Gradle runs.

Then install it on a device:

```powershell
adb install S:\anya-projects\dice-roller\app\build\outputs\apk\debug\app-debug.apk
```

### The Projects tab

Click **🗂 Projects** in the header (or the *Projects* tab in the side panel). It
shows what she is working on, live:

- **Current work** — the project the tab is focused on, persisted across restarts
  (`anya-ui\current.txt`), so "what is she doing" is always one click away.
- **All projects** — newest first. Click one to focus it.
- **One project** — its **task list** (add; click to move `todo → doing → done`),
  its **files**, and a viewer to open a file. Under it sit three buttons:
  **Open folder** (opens that project in Windows Explorer), **Keep working**
  (unattended mode, below) and **Delete** (removes the project and every file in
  it, after a confirmation).
- **History** — every action logged against it (created, wrote a file, ran a
  command, built), so you can retrace her steps.
- **Approvals** — a write that pointed *outside* `S:\anya-projects` waits here for
  your **Approve** / **Deny**.

### Working on a project unattended

**Keep working** lets her keep going without you feeding her the next step. Type
what you want done in the box (or leave it blank to "make progress and get it to
build") and press the button. She then loops on her own — reads a file, writes a
file, updates a task, builds — feeding each result back into the next step, and
streams the whole run into the **Unattended work** log so you can watch.

It stops by itself when she says she is done, if she starts repeating a step, or
after a set number of steps — and the button turns into **Stop working** at any
time. Everything still goes through the same sandbox: writes stay in the
workspace, commands stay on the allow-list, and anything outside still waits for
your approval.

### The rules (why this is safe to leave on)

The sandbox is **`S:\anya-projects`**; everything below is enforced by
`anya-ui\projects.py`, not by her good behaviour:

- She **cannot write outside** it. A path with `..` is refused outright; an
  absolute path outside becomes a **pending approval** you must accept, and
  nothing is written until you do.
- Only an **allow-list** of tools runs — `gradlew`, `gradle`, `java`, `javac`,
  `kotlinc`, `python`, `git`, `adb`, `aapt2`, `apksigner`, `zipalign`, `d8`,
  `keytool` — and shell metacharacters (`;`, `|`, `&`, `>`, `<`, `` ` ``, `$`) plus
  `rm`/`del`/`rd`/`format` are rejected before anything starts.
- A new Android project starts from an **Android Studio scaffold**, so the first
  build works even if she then writes something that does not compile.

### Turning it on and off

Projects are on by default. The **Settings** tab has the switch
(*let her create projects, write files and build*) and the workspace path — the
same way the **Web** switch works. Turn it off and she is back to only writing
code for you to copy.

### Test it

```powershell
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py --build   # includes a real APK build
```

`anya-ui\selftest.py` on its own checks all the offline plumbing: the scaffold,
the package rewrite, tasks, the file sandbox, the approvals flow, the command
allow-list, and every trigger phrase.

---

## 13. Anya on your phone

Anya normally listens on `127.0.0.1`, which means **only this PC** can reach
her. Flip the switch and she also listens on your network, so your phone (or
tablet, or another laptop) can open her in a browser.

### Turning it on

**Settings → Phone access**. Turn on *Let my phone reach Anya*, pick how you
want to get there, and press **Save**.

| Route | Works | Needs |
|---|---|---|
| **This Wi-Fi only** | at home, on the same network | nothing |
| **Tailscale** | anywhere, even over mobile data | [Tailscale](https://tailscale.com) installed on both devices |
| **Cloudflare tunnel** | anywhere, no account | internet; Anya offers to fetch `cloudflared` for you |

Once it's on, the panel shows a **QR code** and the **key**. You have three
ways in:

1. **Scan the QR** with your phone's camera — it opens the right address with
   the key already in the link.
2. **Type the link** by hand (e.g. `http://192.168.1.177:8091/?k=...`).
3. **Open the plain address** and type the key on the unlock page.

After the first successful key, the phone stores a cookie, so you don't have to
do it again on that device.

### How the key works

- Requests **from this PC** (`127.0.0.1`) are always allowed — no key, ever.
- Requests **from anywhere else** must present the key: in the link (`?k=`),
  in a cookie, or in the `X-Anya-Key` header.
- The key is generated once and kept in `anya-ui\config.json`
  (`remote_token`). Press **New key** in Settings to roll it — every phone then
  has to be re-added.
- The URL's `?k=` part is **stripped from the address bar** and turned into the
  cookie as soon as you land, so the key doesn't sit in your history.
- `/api/health` is exempt so the launcher can poll her before unlocking.

The QR is generated locally by `anya-ui\qr.py` — a small encoder written from
scratch (no third-party library, nothing sent anywhere).

### Turning it off

Switch *Phone access* back off and save. She goes back to `127.0.0.1` only. If
you used the Cloudflare tunnel, press **Stop tunnel** as well.

> **Safety:** the key is the only thing between your phone and Anya's Projects
> sandbox, so treat it like a password. Only turn this on when you want remote
> access, and roll the key if you read it out loud or paste it somewhere.

---

## 14. Updating Anya

Anya can update **herself** from GitHub.

**Settings → Updates → Check for updates.** She reads the newest release from
`SeanTheGoon67/Anya-AI` and compares it to `VERSION` in her folder. If there's
something newer, the button becomes **Update now**.

How the update is applied depends on how you installed her:

| Your copy | What she does |
|---|---|
| **Cloned with `git`** | `git fetch --tags --prune` then `git pull --ff-only` |
| **Downloaded as a ZIP** | downloads the release ZIP and lays it over the source |

Either way, **your data is never touched.** The overlay explicitly skips:

- `anya-ui\config.json` (your settings, theme, key)
- `anya-ui\anya_chats.db` (your chat history)
- `anya-ui\approvals.json` and `anya-ui\current.txt`
- `models\`, `lora\`, `dataset\`, `logs\`
- `tools\cloudflared\` (the tunnel helper)
- anything under `S:\anya-projects` (your projects)

When the files are in place she restarts herself to pick them up. If you'd
rather do it by hand, every release also has a normal ZIP on the
[releases page](https://github.com/SeanTheGoon67/Anya-AI/releases).

---

## 15. Anya's mobile UI

There is no separate phone app — **the same page adapts**. Open Anya on a phone
and you get:

- **A drawer, not a squeezed sidebar.** The chat list slides in from the left
  with a dark scrim behind it; tap the scrim (or pick a chat) to close it. The
  ☰ button in the top bar toggles it.
- **A shorter top bar** — labels drop off and only the icons stay, so nothing
  wraps.
- **A full-width panel.** Power, Memory, Projects and the rest fill the screen
  instead of sitting in a cramped column.
- **No iOS zoom.** Text boxes are 16 px, which is the threshold below which
  Safari zooms the page when you tap into them.
- **A reachable composer.** The input row respects the home-bar area
  (`env(safe-area-inset-*)`), so the send button isn't under your thumb-swipe
  zone.
- **No sideways scrolling** at 360 px or 390 px wide.

If your browser blocks site storage, Anya still boots — all storage access is
wrapped, so a locked-down browser degrades instead of breaking.

---

## 16. Wrapping up — the health check

Any time something feels off:

```powershell
S:\envs\ai\Scripts\python.exe anya-ui\selftest.py
```

It checks the model, the memory file, the chat database, the sandbox, the
web switch, voice plumbing, phone-access helpers, the updater and the QR
encoder, then prints a per-section report. Add `--voice`, `--web` or `--build`
to include the heavier end-to-end tests.
