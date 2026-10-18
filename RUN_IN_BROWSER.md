# Running Anya in your browser

> **Heads up — there is a better page now.** Anya's own app
> (**`anya-ui\README.md`**, desktop **`Anya`** icon) has saved history, export
> and a memory limiter, and it manages this same `llama-server` for you. Use it
> unless you specifically want the raw llama.cpp page described below.
>
> Note that the app in §10 of `GUIDE.md` *owns* port 8090: if it is running,
> pressing **Off** there stops the server this document starts.

A ChatGPT-style chat page that runs **entirely on this PC**. It uses
`llama-server` from llama.cpp, which reads Anya's GGUF file directly, so it does
**not** need Ollama at all.

---

## 1. The 10-second version

Double-click **`Anya (browser)`** on your desktop — the icon with her portrait.

It waits for the model to finish loading and **only then** opens the page at
**<http://127.0.0.1:8090>**, so you never land on *"server unavailable"*. Type in
the box at the bottom and press Enter.

> The older `llama-ui.lnk` is a plain Brave web-app shortcut with no server
> behind it — that is what produced *"server unavailable"*. Delete it if it
> confuses you.

---

## 2. What that launcher actually does

```
Start Anya (browser).cmd
        |
        +-- powershell -File anya-web.ps1
                  |
                  +-- kills any old llama-server (frees the port)
                  +-- starts  S:\tools\llama-vulkan\llama-server.exe
                  |     -m  models\anya-f16.gguf      (the model)
                  |     --host 127.0.0.1 --port 8090 (the web address)
                  |     -c 8192                       (context size)
                  |     -ngl 99                       (all layers on the GPU)
                  +-- waits for http://127.0.0.1:8090/health
                  +-- opens  http://127.0.0.1:8090  in your browser
```

It runs **detached**, so the chat server keeps running after the launcher window
closes.

---

## 3. Start it by hand instead

```powershell
cd "C:\Users\Administrator\Documents\Default Project"
.\anya-web.ps1
```

Or run the server yourself, with nothing else in between:

```powershell
S:\tools\llama-vulkan\llama-server.exe `
  -m "C:\Users\Administrator\Documents\Default Project\models\anya-f16.gguf" `
  --host 127.0.0.1 --port 8090 -c 8192 -ngl 99
```

Then open <http://127.0.0.1:8090>.

---

## 4. Using the page

- **Chat** — type in the box at the bottom, press Enter.
- **New chat** — the `+` / new-session button in the sidebar.
- **System prompt** (gear/settings) — paste this so her personality is always
  right, even though it is also trained in:

  ```
  You are Anya, a friendly assistant that runs entirely offline on this PC.
  Your name is Anya. Chat normally, and write code in fenced blocks when asked.
  ```

- **Stop the server when you are done** (it holds ~4 GB of VRAM while idle):

  ```powershell
  Get-Process llama-server | Stop-Process
  ```

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `couldn't bind HTTP server socket` | The port is taken. Use another, e.g. add `--port 8091`, then open that URL. (Port **8080** is used by Steam on this PC.) |
| Browser shows "can't reach this page" | The model is still loading — big files take ~20-30 s. Check `S:\tools\logs\llama-server.err.log`. |
| Everything is very slow | Another app is using the GPU. Run `ollama stop anya`, close games/Chrome tabs, or start with `-ngl 0` to use the CPU. |
| Out of VRAM / errors on load | Lower the context: replace `-c 8192` with `-c 4096`. |
| Want it on a different address | `--host 0.0.0.0` exposes it to your LAN — leave it as `127.0.0.1` unless you know why. |

Logs:
- `S:\tools\logs\llama-server.err.log` (startup + errors)
- `S:\tools\logs\llama-server.out.log` (requests)

---

## 6. Files involved

| File | Purpose |
|---|---|
| **Desktop: `Anya (browser).lnk`** | **the one you want** — starts the server, waits for ready, opens the page |
| `tools\anya-launch.ps1` | the logic behind that desktop icon |
| `anya.ico` / `anya.png` | Anya's icon, from `assets\anya-source.jpg` (regenerate: `python tools\make_icon.py`) |
| `Start Anya (browser).cmd` | older launcher, shows a console window |
| `anya-web.ps1` | the PowerShell logic behind the older launcher |
| `S:\tools\llama-vulkan\llama-server.exe` | the web server + built-in chat UI |
| `models\anya-f16.gguf` | Anya's weights (F16, ~3 GB) |
| `S:\tools\logs\llama-server.*.log` | server logs |

> **Note:** to pick up a *newly trained* Anya, stop the server, then re-run the
> launcher — it always loads `models\anya-f16.gguf` fresh.
