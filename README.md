# Rozefield progress — 77.04%

`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱` **77.04%**

OverField preservation: run the game on your own server after the official one closes.

| Area | Progress | |
|---|---|---:|
| Preservation & archive | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱` | **93.8%** |
| Server & connection | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱` | **71.9%** |
| Content (Global + CN) | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱` | **87.5%** |
| Gameplay | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱` | **55.0%** |

🟩 done · 🟨 in progress · 🟥 blocked · ⬛ not yet

## Preservation & archive — 93.8%

| | Item | Status |
|---|---|---|
| 🟩 | Global client backup (playable copy) | done |
| 🟩 | CN 1.1.12 client copy (source of CN content) | done |
| 🟩 | Protocol recovered: 154 proto files, 2,308 messages, 733 message ids | done |
| 🟩 | Official traffic captures (redacted copies in repo) | done |
| 🟩 | Archived account (Player) imported and playable | done |
| 🟩 | Public snapshot of 490 other players | done |
| 🟨 | Player backup tool RozefieldBackup.exe | in progress — built; first live run waits for the official server to come back |
| 🟩 | Import backup from the login window | done |

## Server & connection — 71.9%

| | Item | Status |
|---|---|---|
| 🟩 | Dispatch, HTTPDNS and region info | done |
| 🟩 | Login window with account picker | done |
| 🟩 | Patch delivery through the game's own updater | done |
| 🟨 | Client requests with a server handler | `▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱` 35.97% 109/303 |
| 🟨 | Requests seen in real play that are handled | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱` 95.60% 87/91 |
| ⬛ | Multiplayer (other players in scenes, co-op) | not yet — phase 2 |

## Content (Global + CN) — 87.5%

| | Item | Status |
|---|---|---|
| 🟩 | CN-only table rows merged into Global data | done |
| 🟩 | CN-only assets ported through the updater (1,120) | done |
| 🟩 | CN-only text translated to English | done |
| 🟨 | English UI after the CN patch | in progress — fix shipped, needs an in-game check |

## Gameplay — 55.0%

| | Item | Status |
|---|---|---|
| 🟩 | New account start, characters, team | done |
| 🟩 | Outfits, gear equip, weapon / armor enhance | done |
| 🟩 | Shops (Rhombite shop gives the item) | done |
| 🟩 | Food buffs and item use | done |
| 🟩 | Channels, scenes, fields, friends' gardens | done |
| 🟨 | Chat and GM console (no double text) | in progress — needs in-game check |
| 🟨 | Umbrella / badge / tool appearance | in progress — needs in-game check |
| 🟨 | Garden plaza: lift, presets, 500,000 limit | in progress — needs in-game check |
| 🟩 | Recruit banners and pulls | done |
| 🟥 | Recruit result screen (animation, can't leave) | blocked — needs the game's Player.log |
| 🟨 | Quest engine: main story, story rewards, daily, delegate | in progress |
| 🟨 | Quest steps with an event rule | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 97.71% 1,236/1,265 |
| 🟨 | Main story quests cleared by an automated new account | `▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱` 16.67% 108/648 |
| 🟨 | Achievements: view archived progress | in progress |
| ⬛ | Achievements: earn and claim | not yet |
| 🟨 | Dye | in progress — colorants not consumed yet |
| 🟨 | Scrap (disassemble) | in progress |
| 🟨 | Life skills: cooking, sewing, making, handicraft, fishing | in progress — recipes, success chance, levels, skills, handbook rewards; needs in-game check |
| 🟨 | Gathering tools (net, axe, hammer, gloves, bottle) | in progress — gather rewards + tool progress; needs in-game check |
| 🟨 | Dungeons (story, resource), vitality, sweep, monster drops | in progress — rewards from the game tables; needs in-game check |
| ⬛ | Field treasure chests (rewards are server-side, not in client data) | not yet |
| ⬛ | Mini-games and co-op (game hall) | not yet |
| 🟨 | Perform (instruments, emotes) | in progress |

**Quest steps with a rule:** 1,236 / 1,265 (`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱` 97.7%)

![Rozefield progress chart](docs/progress.png)

_Updated 2026-11-24 by `py server/tools/progress.py` from [docs/checklist.json](docs/checklist.json)._

## About

Rozefield preserves OverField: the archived client and a private server that runs it after the official shutdown.

- [Archive notes: client build, endpoints, protocol, captures](docs/ARCHIVE.md)
- [Server: setup, login window, backup / import, GM commands](server/README.md)
- [Checklist (plain)](docs/PROGRESS.md)
