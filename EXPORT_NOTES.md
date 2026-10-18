# After training finishes

```powershell
cd "C:\Users\Administrator\Documents\Default Project"
. .\env.ps1

# 1. merge LoRA -> full HF model
llamafactory-cli export .\train\export.yaml

# 2. import into Ollama as "anya"
ollama create anya -f .\Modelfile

# 3. run it
ollama run anya

# 4. compare against the base
ollama run qwen2.5-coder:7b
```

## Notes

- `ollama create` reads the safetensors in `models/qwen2.5-coder-1.5b-merged`
  and converts them; no separate GGUF step needed.
- The `Modelfile` sets the name **Anya** via its `SYSTEM` prompt. To change the
  personality, edit that line and re-run `ollama create anya -f .\Modelfile`
  (no retraining required).
- If the merge fails on memory (16 GB RAM), lower `export_size` to `2` or `1`.
- 1.5B is small and fast; expect it to be *worse* than the 7B at raw coding,
  but tuned toward the formatting/behavior in your dataset.

See **GUIDE.md** for everyday use.
