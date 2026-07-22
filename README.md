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
| `← →` | Pick an option on a choice slot; *type* for anything else |
| `Shift+Enter` | Newline inside a slot |
| `Ctrl+N` / `Ctrl+Shift+N` | New template / new tab |
| `F2` / `Shift+F2` | Edit template / rename tab |
| `Ctrl+D` | Duplicate template |
| `Ctrl+Del` / `Ctrl+Shift+Del` | Delete template / delete tab |
| `Ctrl+←→↑↓` | Reorder the selected tile |
| `Ctrl+Shift+← →` | Move the current tab |
| `Ctrl+,` | **Settings** — colours, fonts, layout, with live preview |
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
        "body": "Refactor this {{language|Python|Go|Rust}} code for {{goal}}." } ] } ] }
```

| Written | Means |
|---|---|
| `{{name}}` | a fill-in slot |
| `{{name\|default}}` | …with a default |
| `{{name\|one\|two\|three}}` | …offered as a choice, `one` preselected |
| `{{name\|\|two\|three}}` | …a choice with nothing preselected |
| `{{name\|a \\\| b}}` | a default containing a literal `\|` |

On Enter:

1. a value you chose or typed wins,
2. otherwise the default — the first option, for a choice — is used,
3. otherwise the literal `{{name}}` is pasted — nothing is ever silently dropped,
   so you can finish the prompt in the chat box.

The same `{{name}}` used twice shares one input and fills every occurrence.

### The fill panel

```
┌─ PCC ─────────────────────────────────────────────────┐
│ Refactor for readability                              │
│ LANGUAGE                                              │
│ [ Python ] [ TypeScript ] [ Go ] [ Rust ] ( custom… ) │
│ GOAL                                                  │
│ [ readability ] [ performance ] ( custom… )           │
│ PREVIEW                                               │
│ Refactor the following Python code for readability…   │
│ ⇥/⇧⇥ next slot · ←→ option · type your own · ⏎ paste  │
└───────────────────────────────────────────────────────┘
```

`←→` walks the options and selects as it goes — there is no separate confirm
step, the same way `←→` edits a row in the settings panel. Options are
shortcuts, never a closed set: **just start typing** and the row hands the
keystroke to a text field, and `Tab` moves on to the next slot. A choice slot's
field only appears once you ask for it, so a panel of choices stays one line per
slot.

## Appearance

Press **`Ctrl+,`** inside the palette (or tray → *Settings…*).

```
┌─ PCC ─────────────────────────────────────────────────┐
│ SETTINGS                                              │
│ ▸ Colour scheme                        ●●● ‹ Cyber ›  │  ← accent / secondary
│   the whole palette                                   │    / background dots
│   Font                          ‹ Cascadia Code ›     │
│   Font size                              ‹ 13 px ›    │
│   Body text                          ‹ monospace ›    │
│   Columns                                    ‹ 3 ›    │
│ ↑↓ setting · ←→ change · PgUp/PgDn ×5 · ⏎ save · Esc revert │
└───────────────────────────────────────────────────────┘
```

`↑↓` picks a setting, `←→` changes it, `PgUp`/`PgDn` steps numbers by five.
**Every change applies instantly** — the panel you're editing is the preview.
`Enter` saves; `Esc` reverts the *entire* session, so trying seven colour
schemes costs nothing.

### Colour schemes

`Cyber` · `Synthwave` · `Matrix` · `Amber` · `Ice` · `Void` · `Blood`

Each scheme is defined by only three colours — background, accent, secondary —
and the other twenty tokens are derived ([schemes.py](pcc/ui/schemes.py)).
Surfaces are lifted toward a desaturated tint of the *accent* rather than
toward neutral grey, which is what makes panels read as part of the theme
instead of grey boxes on a coloured background. Adding a scheme is three hex
codes, and the test suite checks WCAG contrast on all of them.

The window's own border is the exception to that restraint: it is mixed most of
the way to the accent and drawn 2 px, over a shadow carrying the accent's hue.
The palette is summoned over an unknown desktop, so where it *stops* has to be
legible before anything inside it is.

Set `"accent": "#FF8800"` in `settings.json` to override any scheme's accent;
every derived colour follows.

### settings.json

Written on first run to `%APPDATA%\PCC\settings.json`. Everything above is
editable there too — `Ctrl+Shift+R` (or tray → *Reload settings*) restyles in
place, and `Ctrl+Shift+E` opens the file.

| Key | Default | Effect |
|---|---|---|
| `scheme` | `cyber` | Colour scheme name |
| `accent` | `null` | Hex override for the scheme's accent |
| `font_family` | `Cascadia Code, …` | UI font; comma-separated, first installed wins |
| `font_size` | `13` | Base px, clamped 8–28. **Every other size derives from it** |
| `mono_preview` | `true` | `false` → proportional body text (prose skims better) |
| `preview_font_family` | `Segoe UI, Inter, sans-serif` | Face used when `mono_preview` is off |
| `window_width` / `window_height` | `720` / `520` | Palette size in logical px |
| `columns` | `3` | Tiles per row |
| `margin` | `40` | Inset from the active monitor's work area |
| `paste_key` | `ctrl+v` | Use `shift+insert` for terminals that ignore Ctrl+V |
| `restore_clipboard` | `true` | Put your previous clipboard back after pasting |
| `library_path` | `null` | Point `templates.json` somewhere git-tracked |

Sizes scale by ratio rather than fixed offsets, so the hierarchy holds up as
`font_size` grows; tiles re-measure their own text on `FontChange`, so rows stay
aligned and text still elides on a whole-line boundary.

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
| [pcc/ui/schemes.py](pcc/ui/schemes.py) | Colour schemes; 3 source colours → 21 derived tokens |
| [pcc/ui/theme.py](pcc/ui/theme.py) | Resolves `theme.qss` against settings |
| [pcc/ui/settings_panel.py](pcc/ui/settings_panel.py) | The `Ctrl+,` panel |
| [pcc/ui/fill.py](pcc/ui/fill.py) | Slot fields, option chips, live preview |
| [pcc/ui/flow.py](pcc/ui/flow.py) | Wrapping layout used by the option chips |
| [pcc/ui/](pcc/ui/) | Palette, grid, tiles, editor |

## Development

```powershell
$py = "E:\Prpjects\2026\PCC\.venv\Scripts\python.exe"

& $py -m pytest tests            # 298 unit tests, runs locked/headless
& $py -m pcc --show              # run with a console attached
$env:PCC_TIMING=1; & $py -m pcc  # log show latency to stderr
```

Widget tests use Qt's `offscreen` platform plugin, so grid navigation, key
routing, option chips, fill rendering and authoring are all covered without a
visible desktop.

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
