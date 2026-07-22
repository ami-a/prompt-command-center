# PCC — Prompt Command Center

A keyboard-first prompt palette for Windows. Press **CapsLock+Space** anywhere,
pick a template with arrows or by typing, hit **Enter**, and it pastes straight
back into whatever text box you were in.

```
┌─ PCC ─────────────────────────────────────────────┐
│  PCC   [ type to filter…                       ]  │
│  Coding 1   Writing 2   Thinking 3                │
│  ─────────                                        │
│  ▸ Refactor for readability 3⬚   Explain this…    │
│    Refactor the following Python  Explain what…   │
│                                                   │
│  ↑↓←→ move · ⏎ paste · ^⏎ raw · Esc hide          │
└───────────────────────────────────────────────────┘
```

## Install

```powershell
powershell -ExecutionPolicy Bypass -File E:\Prpjects\2026\PCC\scripts\setup.ps1
```

Creates the venv, installs dependencies, runs the tests, adds
`#Include …\scripts\pcc.ahk` to `a001.ahk` (with a backup), and drops a Startup
shortcut. Re-running it is safe.

Then reload AutoHotkey and press **CapsLock+Space**.

## Keys

| Key | Action |
|---|---|
| `CapsLock+Space` | Show the palette |
| *type* | Fuzzy-filter across **all** tabs; top hit auto-selected |
| `↑ ↓ ← →` | Move between tiles |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab |
| `Alt+1..9` | Jump to tab N |
| `Enter` | Paste — or open the fill panel if the template has slots |
| `Ctrl+Enter` | Paste immediately, skipping the fill panel |
| `Esc` | Clear the search, then hide |
| `Tab` / `Shift+Tab` | Next / previous slot (fill panel) |
| `Shift+Enter` | Newline inside a slot |
| `Ctrl+N` / `Ctrl+Shift+N` | New template / new tab |
| `F2` / `Shift+F2` | Edit template / rename tab |
| `Ctrl+D` | Duplicate template |
| `Ctrl+Del` / `Ctrl+Shift+Del` | Delete template / delete tab |
| `Ctrl+←→↑↓` | Reorder the selected tile |
| `Ctrl+Shift+← →` | Move the current tab |
| `Ctrl+E` / `Ctrl+R` | Open `templates.json` / reload it |
| `Ctrl+Shift+E` / `Ctrl+Shift+R` | Open `settings.json` / reload + restyle live |

## Templates

Stored at `%APPDATA%\PCC\templates.json`, editable in the app or by hand — the
file is watched and reloads live.

```json
{ "version": 1,
  "tabs": [ { "id": "t_coding", "name": "Coding", "templates": [
      { "id": "p_refactor",
        "title": "Refactor for readability",
        "body": "Refactor this {{language|Python}} code for {{goal}}." } ] } ] }
```

`{{name}}` marks a fill-in slot; `{{name|default}}` gives it a default. On Enter:

1. a value you typed wins,
2. otherwise the default is used,
3. otherwise the literal `{{name}}` is pasted — nothing is ever silently dropped,
   so you can finish the prompt in the chat box.

The same `{{name}}` used twice shares one input and fills every occurrence.

## Appearance and fonts

`%APPDATA%\PCC\settings.json` is written on first run. Edit it and press
`Ctrl+Shift+R` (or tray → *Reload settings*) — the palette restyles in place, no
restart.

| Key | Default | Effect |
|---|---|---|
| `font_family` | `Cascadia Code, JetBrains Mono, Consolas, monospace` | UI font. Comma-separated fallback list; the first installed one wins |
| `font_size` | `13` | Base size in px, clamped to 8–28. **Every other size derives from it**, so this one number rescales the whole palette |
| `mono_preview` | `true` | `false` renders tile body + preview in a proportional face — prompt text is prose, and prose skims better proportional |
| `preview_font_family` | `Segoe UI, Inter, sans-serif` | The proportional face used when `mono_preview` is `false` |
| `window_width` / `window_height` | `720` / `520` | Palette size in logical px |
| `columns` | `3` | Tiles per row |
| `margin` | `40` | Inset from the active monitor's work area |
| `paste_key` | `ctrl+v` | Use `shift+insert` for terminals that ignore Ctrl+V |
| `restore_clipboard` | `true` | Put your previous clipboard back after pasting |
| `library_path` | `null` | Point `templates.json` somewhere git-tracked |

Sizes scale by ratio rather than fixed offsets, so the visual hierarchy holds up
when you change `font_size`; tiles re-measure their own text on `FontChange`, so
rows stay aligned and text still elides on a whole-line boundary.

## How it works

```
CapsLock+Space
  └─ AHK: PostMessage WM_APP → hidden window "PCC_IPC_HOST"   (~1 ms, no spawn)
       └─ capture GetForegroundWindow()  ← before we show, so we know the target
          position on the active monitor · show · take foreground
             └─ Enter: clipboard ← text · hide · restore focus · SendInput Ctrl+V
                       └─ 300 ms later: previous clipboard restored
```

PCC stays resident in the tray. AHK posts a message rather than launching a
process, because a cold Python+Qt start costs 400–1200 ms and the palette must
feel instant. If the process is not running, AHK starts it and retries — so
killing PCC never requires a reboot.

Three Win32 details do the heavy lifting:

- **`AttachThreadInput` in both directions.** Windows only honours
  `SetForegroundWindow` from the process that already owns the foreground.
  Taking focus (`force_foreground`) and giving it back (`restore_focus`) both
  borrow the other thread's input queue; without this the palette appears
  without keyboard focus and the paste lands in the wrong window.
- **Clipboard + Ctrl+V, not synthesised keystrokes.** O(1) regardless of prompt
  length, and the only method that survives Hebrew/RTL and emoji intact. The
  previous clipboard is restored afterwards.
- **DPI-correct placement.** Qt reports screen *origins* in physical pixels but
  *sizes* in logical ones; on a 175 % display, scaling both puts the window off
  screen. See `placement.physical_geometry`.

## Layout

| Path | Role |
|---|---|
| [pcc/model.py](pcc/model.py) | Templates, tabs, `{{slot}}` grammar, rendering |
| [pcc/store.py](pcc/store.py) | Atomic JSON, corruption recovery, file watching |
| [pcc/winapi.py](pcc/winapi.py) | Foreground capture/restore, clipboard, `SendInput` |
| [pcc/ipc.py](pcc/ipc.py) | The hidden window AHK posts to |
| [pcc/placement.py](pcc/placement.py) | Multi-monitor, DPI-aware positioning |
| [pcc/search.py](pcc/search.py) | Prefix → acronym → subsequence → fuzzy ranking |
| [pcc/ui/](pcc/ui/) | Palette, grid, tiles, fill panel, editor, theme |

## Development

```powershell
$py = "E:\Prpjects\2026\PCC\.venv\Scripts\python.exe"

& $py -m pytest tests            # 111 unit tests, runs locked/headless
& $py -m pcc --show              # run with a console attached
$env:PCC_TIMING=1; & $py -m pcc  # log show latency to stderr
```

Widget tests use Qt's `offscreen` platform plugin, so grid navigation, key
routing, fill rendering and authoring are all covered without a visible desktop.

What that *cannot* cover is the Win32 half — taking the foreground, synthesising
Ctrl+V, and landing text in another process. For that:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
```

It drives the real app end to end against a real paste target and checks focus
acquisition, defaults, literal-token fallback, Esc-without-pasting, show latency
and memory. **It needs an unlocked, interactive session** — Windows refuses
foreground changes, screen reads and synthetic input while locked, so the script
detects that and exits rather than reporting false failures.

`spike/` holds the lower-level harness used to prove the trigger→focus→paste
chain in isolation; `spike/host.py` is a standalone reproduction if that path
ever regresses.

## Known limitations

- **Elevated windows.** If the focused app runs as administrator and PCC does
  not, Windows UIPI blocks `SendInput` and the paste silently fails. Run PCC
  elevated too if you need this.
- **Locked session.** Nothing can take the foreground while Windows is locked;
  the trigger is a no-op until you unlock.
- **Clipboard restore is text-only.** If the clipboard held an image or files,
  PCC leaves the pasted text there rather than replacing your data with an
  empty string.
