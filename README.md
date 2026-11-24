# Rozefield progress — 81.47%

`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱` **81.47%**

OverField preservation: run the game on your own server after the official one closes.

| Area | Progress | |
|---|---|---:|
| Preservation & archive | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱` | **93.8%** |
| Server & connection | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱` | **83.3%** |
| Content (Global + CN) | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱` | **87.5%** |
| Gameplay | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱` | **61.3%** |

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

## Server & connection — 83.3%

| | Item | Status |
|---|---|---|
| 🟩 | Dispatch, HTTPDNS and region info | done |
| 🟩 | Login window with account picker | done |
| 🟩 | Patch delivery through the game's own updater | done |
| 🟩 | Client requests with a server handler | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 303/303 |
| 🟩 | Requests seen in real play that are handled | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 136/136 |
| ⬛ | Multiplayer (other players in scenes, co-op) | not yet — phase 2 |

## Content (Global + CN) — 87.5%

| | Item | Status |
|---|---|---|
| 🟩 | CN-only table rows merged into Global data | done |
| 🟩 | CN-only assets ported through the updater (1,120) | done |
| 🟩 | CN-only text translated to English | done |
| 🟨 | English UI after the CN patch | in progress — fix shipped, needs an in-game check |

## Gameplay — 61.3%

| | Item | Status |
|---|---|---|
| 🟩 | New account start, characters, team | done |
| 🟩 | Outfits, gear equip, weapon / armor enhance | done |
| 🟨 | Character level up, level break, star up, skill up | in progress — costs from the game tables; needs in-game check |
| 🟨 | Profile, outfit / gear presets, pets, visit a friend's garden | in progress — needs in-game check |
| 🟩 | Shops (Rhombite shop gives the item) | done |
| 🟩 | Food buffs and item use | done |
| 🟩 | Channels, scenes, fields, friends' gardens | done |
| 🟨 | Chat and GM console (no double text) | in progress — needs in-game check |
| 🟨 | Umbrella / badge / tool appearance | in progress — needs in-game check |
| 🟨 | Garden plaza: lift, presets, 500,000 limit | in progress — needs in-game check |
| 🟩 | Recruit banners and pulls | done |
| 🟨 | Recruit result screen (animation, can't leave) | in progress — results now carry the official bonus items + quality; needs in-game check |
| 🟨 | Quest engine: main story, story rewards, daily, delegate | in progress |
| 🟨 | Quest steps with an event rule | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 97.71% 1,236/1,265 |
| 🟩 | Main story quests cleared by an automated new account | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 648/648 |
| 🟨 | Achievements: view archived progress | in progress |
| 🟨 | Achievements: earn and claim | in progress — counted from play, claim + group rewards; needs in-game check |
| 🟨 | Dye | in progress — colorants not consumed yet |
| 🟨 | Scrap (disassemble) | in progress |
| 🟨 | Life skills: cooking, sewing, making, handicraft, fishing | in progress — recipes, success chance, levels, skills, handbook rewards; needs in-game check |
| 🟨 | Gathering tools (net, axe, hammer, gloves, bottle) | in progress — gather rewards + tool progress; needs in-game check |
| 🟩 | Dungeons (story, resource), vitality, sweep, monster drops | done — official flow from capture: final chest -> temp storage -> pickup; 38 dungeons' chest contents observed |
| 🟨 | Field treasure chests, encounters, riddles, challenges, moons | in progress — 1300 chest positions + your opened-chest state imported; encounter/dynamic chest per capture; field chest amounts approximated |
| 🟨 | Co-op games: Pop Balloons, Aerial Adventure (solo or with players on this server) | in progress — from the 2026-11-25 capture; only 2 platform layouts + 1 balloon layout were seen; needs in-game check |
| 🟨 | Perform (instruments, emotes) | in progress |
| 🟨 | Events: Pass, Gashapon, 7-day sign-in (official flow) | in progress — from the 2026-11-24 capture; needs in-game check |
| 🟨 | Wishing tree and Wish Stone exchange | in progress — from the capture; Wish Stone income is estimated |
| 🟨 | Abyss: info, teams, team switch, best time | in progress — from the capture |
| 🟨 | Group emotes, dice, friend gifts (friendship points) | in progress — from the capture |
| 🟨 | Energy / vitality purchases (official prices) | in progress — needs in-game check |
| 🟨 | Exploration (send a team out), team exploration | in progress — reward amounts estimated |
| 🟨 | Handbook, imprint, treasure, badge, character achievement rewards | in progress — table rewards where the game has them, else estimated |
| 🟨 | Field extras: coins, digging, supply box, campfire, sitting, clap, music notes | in progress — needs in-game check |
| 🟩 | Redemption codes (server owner sets them in save/codes.json) | done |
| 🟨 | Boss Rush (solo), Abyss quest rewards | in progress — needs in-game check |
| 🟨 | Gomoku vs AI reward, pet release, gift-bag bulk open, lock gear | in progress — needs in-game check |
| 🟨 | Multiplayer: other players in the same scene, movement, emotes, group emotes, chat (nearby, world, private), sitting | in progress — tested with 2 local clients; needs in-game check |
| 🟨 | Part-time tasks, Moon Points to Wish Stones (official step prices), co-op ticket refill (6 a day) | in progress — Moon Points per activity: 5 / 25 as seen |
| 🟨 | Online Gomoku (2 players) | in progress — reward amounts estimated |
| 🟨 | Photo wall (upload, browse, like, favourite, delete) | in progress — pictures are stored; whether the client can download them back is untested |
| 🟨 | Rankings: Abyss, Boss Rush (everyone on this server) | in progress |
| 🟨 | Restaurant mini-game (buy, merge, sell, serve, quests) | in progress — built from the game tables; no official capture |
| 🟨 | Field gear drops follow world level, 3% rare top quality | in progress — estimate |
| 🟨 | RozefieldBackup: background start, follows a Steam restart, log file | in progress — needs a live run |

**Quest steps with a rule:** 1,236 / 1,265 (`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱` 97.7%)

![Rozefield progress chart](docs/progress.png)

_Updated 2026-11-25 by `py server/tools/progress.py` from [docs/checklist.json](docs/checklist.json)._

## About

Rozefield preserves OverField: the archived client and a private server that runs it after the official shutdown.

- [Archive notes: client build, endpoints, protocol, captures](docs/ARCHIVE.md)
- [Server: setup, login window, backup / import, GM commands](server/README.md)
- [Checklist (plain)](docs/PROGRESS.md)
