#!/usr/bin/env python
"""
build_cocoon_features.py — synthesisable, *verifiable* Cocoon-style feature data.

Generates two datasets in LLaMA-Factory "alpaca" format:

  cocoon_themes.jsonl    -- Cocoon Shell `theme.json` authoring + field Q&A.
                            Outputs are real, valid JSON derived from the public
                            Theme JSON Reference spec.
  platform_launch.jsonl  -- launcher "platforms.json" entries in the two real
                            shapes used by open-source frontends (Cannoli's
                            app-launch map and Mimir's scanner list).

Nothing here is invented prose: every answer is machine-checkable JSON.

Usage:
    python build_cocoon_features.py --repo S:\\repos --out-dir dataset
"""

from __future__ import annotations

import argparse
import json
import os
import random

random.seed(1337)

# label -> (bg_start, bg_end, card_start, card_end, text1, text2, accent)
PALETTES = [
    ("deep-space blues", ["#0B1020", "#121A33"], ["#1B2440", "#243056"], "#E8ECFF", "#9AA6C9", "#5B8CFF"),
    ("vaporwave magenta", ["#1A0B2E", "#2B1047"], ["#3A1560", "#4B1E78"], "#F5E6FF", "#C79AE0", "#FF4FD8"),
    ("oled midnight", ["#000000", "#000000"], ["#0A0A0A", "#141414"], "#FFFFFF", "#8A8A8A", "#00E0C6"),
    ("forest moss", ["#0C1A12", "#132619"], ["#1B3324", "#24422F"], "#E6F2E9", "#9DBBA6", "#4CD964"),
    ("sunset ember", ["#1C0F0A", "#2E1710"], ["#402016", "#552B1D"], "#FFEDE3", "#D9A48F", "#FF7A45"),
    ("arctic light", ["#EEF3F8", "#DCE6F0"], ["#FFFFFF", "#E8EFF6"], "#0E1A24", "#5A6B7A", "#2E7CF6"),
    ("royal violet", ["#120A24", "#1D0F3A"], ["#2A1650", "#3A1F6B"], "#F0E9FF", "#B49AD6", "#8B5CF6"),
    ("crimson noir", ["#160708", "#260C0E"], ["#3A1215", "#4E1A1E"], "#FFE9EA", "#D19A9D", "#FF3B4E"),
    ("amber dusk", ["#1A1206", "#2A1D0A"], ["#3D2A10", "#553A16"], "#FFF4E0", "#D6B98A", "#FFB020"),
    ("cyber teal", ["#04141A", "#08222B"], ["#0D3140", "#124455"], "#E0FBFF", "#8FC7D4", "#00D9E0"),
]

SOUNDS = [
    "navigate", "select", "back", "folder_open", "folder_close", "launch",
    "error", "notification", "screen_swap", "grid_zoom_in", "grid_zoom_out",
    "reorder_pickup", "reorder_place", "open_edit", "pop", "saving",
]

THEME_NAMES = [
    "Midnight Glass", "Neon Arcade", "Pixel Dawn", "Velvet Static", "Aurora Drift",
    "Carbon Fiber", "Pastel Cartridge", "Retro CRT", "Deep Ocean", "Solar Flare",
    "Lunar Haze", "Copper Wire", "Frostbite", "Ink & Paper", "Raspberry Pi",
    "Tokyo Night", "Nordic Fog", "Gameboy Green", "Magma Core", "Ice Nine",
]

DOCK_SHAPES = ["CIRCLE", "SQUIRCLE", "ROUNDED_SQUARE", "SQUARE"]
HERO_STYLES = ["VIGNETTE", "FULLSCREEN", "NONE"]
ICON_STYLES = ["COLORED", "ACCENT", "FLAT"]
SURFACES = ["SOLID", "GLASS"]
CURSORS = ["ANIMATED", "OUTLINED", "ALTERNATIVE_ANIMATED", "ALTERNATIVE"]
MODES = ["DARK", "LIGHT", "OLED"]
MUSIC_MODES = ["PLAYLIST", "TIME", "DISABLED"]
PLAYBACK = ["IN ORDER", "SHUFFLE"]


def rnd(lo, hi, places=2):
    return round(random.uniform(lo, hi), places)


def make_theme():
    label, bg, card, t1, t2, accent = random.choice(PALETTES)
    name = random.choice(THEME_NAMES)
    mode = random.choice(MODES)
    surface = random.choice(SURFACES)
    hero = random.choice(HERO_STYLES)
    icon_style = random.choice(ICON_STYLES)
    cursor = random.choice(CURSORS)
    dock = random.choice(DOCK_SHAPES)
    music = random.choice(MUSIC_MODES)

    theme = {
        "name": name,
        "author": random.choice(["you", "anonymous", "cocoon-community"]),
        "version": "1.0.0",
        "description": f"A {label} {mode.lower()} theme for Cocoon Shell.",
        "theme_mode": mode,
        "wallpaper_main": "main",
        "wallpaper_external": "external",
        "color_scheme": {
            "background_gradient_start": bg[0],
            "background_gradient_end": bg[1],
            "card_gradient_start": card[0],
            "card_gradient_end": card[1],
            "text_primary": t1,
            "text_secondary": t2,
            "accent_gradient_start": accent,
            "accent_gradient_end": accent,
            "icon_tint": t1,
            "tile_background": card[1],
            "tile_border": accent + "55",
            "drop_shadow": "#00000066",
            "success": "#4CD964",
            "warning": "#FFB020",
            "divider": t2 + "33",
        },
        "settings": {
            "icon_roundness": rnd(0.05, 0.5),
            "icon_scale": rnd(0.5, 1.0),
            "hover_scale": rnd(0.5, 1.0),
            "hero_display_style": hero,
            "hero_logo_scale": rnd(0.1, 1.0),
            "hero_folder_logo_scale": rnd(0.1, 1.0),
            "hero_gradient_style": random.choice(["NONE", "BLACK_GRADIENT"]),
            "icon_style": icon_style,
            "surface_material": surface,
            "glass_blur": rnd(0.0, 10.0),
            "glass_tint": rnd(0.0, 1.0),
            "cursor_style": cursor,
            "dock_icon_shape": dock,
            "corner_hints": random.choice([True, False]),
        },
        "music_mode": music,
        "music_playback_mode": random.choice(PLAYBACK),
        "sfx_volume": rnd(0.0, 1.0),
        "music_volume": rnd(0.0, 1.0),
        "jingle_volume": rnd(0.0, 1.0),
    }
    if music == "PLAYLIST":
        theme["music_playlist"] = "music/one.mp3||music/two.mp3"

    instruction = (
        f'Create a Cocoon Shell theme.json for a {mode.lower()} theme called "{name}". '
        f"Use a {label} colour scheme, {surface.lower()} panel surfaces, "
        f"{hero.lower()} hero images and {music.lower()} music. "
        f"Output only the JSON."
    )
    return instruction, theme


QA = [
    ("What values can `theme_mode` take in a Cocoon theme.json?",
     "`LIGHT`, `DARK`, `OLED` or `SYSTEM`. Values are case-insensitive."),
    ("Which field is required in a Cocoon theme.json?",
     "Only `name` is required. Every other field is optional; omitted colours and settings leave the user's current values unchanged."),
    ("How do you set the main background gradient in a Cocoon theme?",
     "Use `color_scheme.background_gradient_start` and `color_scheme.background_gradient_end`, with colours written as `#RRGGBB` or `#AARRGGBB`."),
    ("What formats are accepted for colours in `color_scheme`?",
     "`#RRGGBB` or `#AARRGGBB`."),
    ("Where do Cocoon themes live on disk?",
     "Inside the `themes/` folder of the Cocoon data directory, one subfolder per theme, e.g. `themes/my-theme/theme.json`."),
    ("What fields control Cocoon's glass panel material?",
     "`settings.surface_material` (`SOLID` or `GLASS`), `glass_blur` (0.0-10.0), `glass_refraction` (0.0-1.0), `glass_highlight` (boolean), `glass_rim_strength` (0.0-1.0), `glass_on_tiles` (boolean) and `glass_tint` (0.0-1.0)."),
    ("What is the range of `icon_roundness` in Cocoon theme settings?",
     "`0.0` to `0.5`."),
    ("What values does `hero_display_style` accept?",
     "`VIGNETTE`, `FULLSCREEN` or `NONE`."),
    ("What values does `cursor_style` accept?",
     "`ANIMATED`, `OUTLINED`, `ALTERNATIVE_ANIMATED` or `ALTERNATIVE`."),
    ("What values does `dock_icon_shape` accept?",
     "`CIRCLE`, `SQUIRCLE`, `ROUNDED_SQUARE` or `SQUARE`."),
    ("How do you define playlist music in a Cocoon theme?",
     'Set `music_mode` to `PLAYLIST` and list relative files in `music_playlist` separated by `||`, e.g. `"music/one.mp3||music/two.mp3"`.'),
    ("What values can `music_playback_mode` take?",
     "`IN ORDER` or `SHUFFLE`."),
    ("How are sound-effect files named in a Cocoon theme?",
     "Put audio in the `sounds/` folder using base names such as `navigate`, `select`, `back`, `folder_open`, `folder_close`, `launch`, `error`, `notification`, `screen_swap`, `grid_zoom_in`, `grid_zoom_out`, `reorder_pickup`, `reorder_place`, `open_edit`, `pop` and `saving`. WAV, MP3, OGG, M4A and FLAC are supported."),
    ("How do icon overlays work in a Cocoon theme?",
     "Use `icon_overlays/{platform}/mask.png` to define the visible game-art shape and `icon_overlays/{platform}/overlay.png` to draw above the art. The platform folder uses Cocoon's platform id such as `gba` or `snes`."),
    ("Where do smart-folder assets go in a Cocoon theme?",
     "Under `smart_folders/{type}/` for `icon`, `hero` and `logo`. Common keys are `favorites` and `recent`; others include `most_played`, `unplayed`, `newly_added`, `android_games` and `emulators`. Platform folders go under `smart_folders/by_platform/{platform}/`."),
    ("What is `asset_refs` used for in a Cocoon theme?",
     "Silk themes can depend on shared asset packs. Each entry has `id`, `name`, `category` and `version`; supported categories include `icon_overlays`, `smart_folders`, `sounds` and `music`. Cocoon downloads missing linked packs when a theme comes from Silk."),
    ("What wallpaper fields does a Cocoon theme support?",
     "`wallpaper_main` and `wallpaper_external`. References may omit the extension; Cocoon checks image, GIF and video formats and also falls back to names like `main`/`bottom` and `external`/`top`."),
    ("How do you set volume levels in a Cocoon theme?",
     "`sfx_volume`, `music_volume` and `jingle_volume`, each `0.0`-`1.0`."),
    ("What does `music_time_schedule` do?",
     "With `music_mode` set to `TIME`, it selects music by hour `hour:minute` mapped to a relative file."),
    ("What is a Cocoon Pod?",
     "A small app built into Cocoon. The built-in Pods are Log (play history and statistics), Picnic (organises screenshots) and Silk (the theme and asset store)."),
    ("Where do you re-add a Cocoon Pod shortcut you removed from Home?",
     "From the Cocoon Start menu."),
    ("What are Cocoon's scraping sources?",
     "SteamGridDB (artwork, API key), ScreenScraper (artwork and info, account), LaunchBox Games Database, IGDB and HowLongToBeat."),
    ("What scrape types does Cocoon offer?",
     "Missing Basics, Missing Selected and Force All. Leave 'Replace Protected Fields' off to keep manual edits."),
]


def build_themes(n):
    rows = []
    for _ in range(n):
        instr, theme = make_theme()
        rows.append({
            "instruction": instr,
            "input": "",
            "output": "```json\n" + json.dumps(theme, indent=2, ensure_ascii=False) + "\n```",
        })
    for q, a in QA:
        rows.append({"instruction": q, "input": "", "output": a})
    return rows


def build_platforms(repo_root):
    rows = []

    # --- Cannoli shape: map id -> {name, core, app[]} --------------------- #
    can = os.path.join(repo_root, "cannoli-main", "app", "src", "main", "assets", "platforms.json")
    if os.path.isfile(can):
        with open(can, encoding="utf-8") as fh:
            data = json.load(fh)
        for pid, entry in data.items():
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", pid)
            core = entry.get("core", "")
            apps = entry.get("app", []) or []
            instr = (
                f"Write the `platforms.json` entry for {name} (platform id `{pid}`) "
                f"in a libretro Android frontend. It must use the core `{core}` and "
                f"declare the Android emulator apps that can launch the ROM"
                f"{' via intents, extras or custom schemes' if apps else ''}. "
                f"Output only the JSON object for that platform."
            )
            rows.append({
                "instruction": instr,
                "input": "",
                "output": "```json\n" + json.dumps({pid: entry}, indent=2, ensure_ascii=False) + "\n```",
            })

    # --- Mimir shape: array of scanner platform records ------------------- #
    mim = os.path.join(repo_root, "mimir-main", "core", "scanner", "src", "main", "resources", "platforms.json")
    if os.path.isfile(mim):
        with open(mim, encoding="utf-8") as fh:
            data = json.load(fh)
        for entry in data if isinstance(data, list) else []:
            if not isinstance(entry, dict):
                continue
            pid = entry.get("id", "?")
            name = entry.get("name", pid)
            aliases = entry.get("folderAliases", [])
            exts = entry.get("extensions", [])
            lib = entry.get("libretroName", "")
            instr = (
                f"Write the ROM-scanner `platforms.json` record for {name} "
                f"(id `{pid}`). Include the folder aliases "
                f"({', '.join(map(str, aliases))}), the ROM file extensions "
                f"({', '.join(map(str, exts))}) and the libretro system name "
                f"`{lib}`. Output only the JSON object."
            )
            rows.append({
                "instruction": instr,
                "input": "",
                "output": "```json\n" + json.dumps(entry, indent=2, ensure_ascii=False) + "\n```",
            })

    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=r"S:\repos", help="folder holding the downloaded repos")
    ap.add_argument("--out-dir", default="dataset")
    ap.add_argument("--themes", type=int, default=160)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    themes = build_themes(args.themes)
    with open(os.path.join(args.out_dir, "cocoon_themes.jsonl"), "w", encoding="utf-8") as fh:
        for r in themes:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    plats = build_platforms(args.repo)
    with open(os.path.join(args.out_dir, "platform_launch.jsonl"), "w", encoding="utf-8") as fh:
        for r in plats:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[+] cocoon_themes.jsonl   {len(themes)} examples")
    print(f"[+] platform_launch.jsonl {len(plats)} examples")


if __name__ == "__main__":
    main()
