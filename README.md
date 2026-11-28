# Rozefield progress — 86.13%

`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱` **86.13%**

| Area | Before (2026-11-26) | Now (2026-11-28) | Done / Total |
|---|---:|---:|---:|
| **Preservation & archive** | 93.8% | **93.8%** | 7 / 8 |
| **Server & connection** | 91.7% | **91.7%** | 5 / 6 |
| **Content (Global + CN)** | 87.5% | **87.5%** | 3 / 4 |
| **Gameplay** | 60.2% | **71.6% (+11.4%)** | 19 / 44 |
| **Overall** | **83.29%** | **86.13% (+2.84%)** | **28 items left** |

OverField preservation: run the game on your own server after the official one closes.

## The three parts

| Part | What it is | Get it |
|---|---|---|
| **Overfield** | The game. Not shared here (it belongs to its makers): use your own copy (Steam or the OverField launcher) and point it at a server with Overfield Backup, or the game package your server owner gives you | your own install |
| **Overfield Backup** (by RozenCrimsonvale) | Save your official account before 8 Feb 2027; **Play on Rozefield** points your own game at a server (a copy, or the game itself) | [Releases](https://github.com/Erorodata/Rozefield/releases/latest): `Overfield-Backup.zip` |
| **Overfield Server** (by RozenCrimsonvale) | Host a server: control panel with a setup wizard, sharing, traffic, imports, moving to another device; Windows, Linux or a VPS | [Releases](https://github.com/Erorodata/Rozefield/releases/latest): `Overfield-Server.zip` |

| Area | Progress | |
|---|---|---:|
| Preservation & archive | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱` | **93.8%** |
| Server & connection | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱` | **91.7%** |
| Content (Global + CN) | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱` | **87.5%** |
| Gameplay | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱` | **71.6%** |

🟩 done · 🟨 in progress (`test` / `retest` / `captured`) · 🟥 blocked · ⬛ not yet

## Preservation & archive — 93.8%

| | Item | Status |
|---|---|---|
| 🟩 | Global client backup (playable copy) | done |
| 🟩 | CN 1.1.12 client copy (source of CN content) | done |
| 🟩 | Protocol recovered: 154 proto files, 2,308 messages, 733 message ids | done |
| 🟩 | Official traffic captures (redacted copies in repo) | done |
| 🟩 | Archived account imported and playable | done |
| 🟩 | Public snapshot of 490 other players | done |
| 🟨 | Player backup tool Overfield Backup.exe | in progress — built; first live run waits for the official server to come back |
| 🟩 | Import backup from the login window | done |

## Server & connection — 91.7%

| | Item | Status |
|---|---|---|
| 🟩 | Dispatch, HTTPDNS and region info | done |
| 🟩 | Login window with account picker | done |
| 🟩 | Patch delivery through the game's own updater | done |
| 🟩 | Client requests with a server handler | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 303/303 |
| 🟩 | Requests seen in real play that are handled | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 140/140 |
| 🟨 | Online play: friends on other PCs (LAN / internet), per-player server address, friend setup script | in progress — needs a test with a second PC |

## Content (Global + CN) — 87.5%

| | Item | Status |
|---|---|---|
| 🟩 | CN-only table rows merged into Global data | done |
| 🟩 | CN-only assets ported through the updater (1,120) | done |
| 🟩 | CN-only text translated to English | done |
| 🟨 | English UI after the CN patch | in progress — fix shipped, needs an in-game check |

## Gameplay — 71.6%

| | Item | Stage | Status |
|---|---|---|---|
| 🟩 | New account start, characters, team | `done` | done |
| 🟩 | Outfits, gear equip, weapon / armor enhance | `done` | done |
| 🟨 | Character level up, level break, star up, skill up | `test` | in progress — costs from the game tables; needs in-game check |
| 🟩 | Profile, outfit / gear presets, pets, visit a friend's garden | `done` | done — confirmed in Build 76 play-test |
| 🟨 | Shops: every shop item shows (pool item index as official), multi-item slots rotate, daily / weekly / monthly limits reset | `retest` | in progress — needs in-game check |
| 🟩 | Food buffs and item use | `done` | done |
| 🟩 | Channels, scenes, fields, friends' gardens | `done` | done |
| 🟩 | Chat and GM console: world and channel history kept across logins and restarts | `done` | done — confirmed in Build 76 play-test |
| 🟨 | Umbrella / badge / tool appearance | `test` | in progress — needs in-game check |
| 🟩 | Garden plaza: lift, presets, 500,000 limit | `done` | done — confirmed in play-test |
| 🟩 | Recruit banners and pulls | `done` | done |
| 🟩 | Recruit result screen (animation, can't leave) | `done` | done — confirmed in Build 51 play-test; results carry official bonus items + quality |
| 🟨 | Quest engine: main story, story rewards, daily, delegate | `retest` | in progress |
| 🟩 | Quest steps with an event rule | `done` | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 1,265/1,265 |
| 🟩 | Main story quests cleared by an automated new account | `done` | `▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.00% 648/648 |
| 🟨 | Achievements: view archived progress | `test` | in progress |
| 🟨 | Achievements: earn and claim | `retest` | in progress — counted from play, claim + group rewards; needs in-game check |
| 🟨 | Dye | `retest` | in progress — each dye uses 1 colorant as official; needs in-game check |
| 🟨 | Scrap (disassemble) | `test` | in progress |
| 🟨 | Life skills: cooking, sewing, making, handicraft, fishing | `test` | in progress — recipes, success chance, levels, skills, handbook rewards; needs in-game check |
| 🟩 | Gathering tools (net, axe, hammer, gloves, bottle) | `done` | done — confirmed in play-test |
| 🟩 | Dungeons (story, resource), vitality, sweep, monster drops | `done` | done — official flow from capture: final chest -> temp storage -> pickup; 38 dungeons' chest contents observed |
| 🟩 | Field treasure chests, encounters, riddles, challenges, moons | `done` | done — confirmed in Build 76 play-test |
| 🟨 | Co-op games: Pop Balloons, Aerial Adventure (solo or with players on this server) | `retest / captured` | in progress — from the 2026-11-25 capture; only 2 platform layouts + 1 balloon layout were seen; needs in-game check |
| 🟩 | Perform (instruments, emotes) | `done` | done |
| 🟩 | Events: Pass, Gashapon, 7-day sign-in (official flow) | `done` | done — confirmed in Build 51 play-test (Event menu clean, table-driven rewards) |
| 🟨 | Wishing tree and Wish Stone exchange | `captured` | in progress — from the capture; Wish Stone income is estimated |
| 🟨 | Abyss: info, teams, team switch, best time | `retest` | in progress — from the capture |
| 🟩 | Group emotes, dice, friend gifts (friendship points) | `done` | done — confirmed in Build 76 play-test |
| 🟨 | Energy / vitality purchases (official prices) | `test` | in progress — needs in-game check |
| 🟨 | Exploration (send a team out), team exploration | `captured` | in progress — reward amounts estimated |
| 🟨 | Handbook, imprint, treasure, badge, character achievement rewards | `retest / captured` | in progress — table rewards where the game has them, else estimated |
| 🟨 | Field extras: coins, digging, supply box, campfire, sitting, clap, music notes | `test / captured` | in progress — needs in-game check |
| 🟩 | Redemption codes (server owner sets them in save/codes.json) | `done` | done |
| 🟨 | Boss Rush (solo), Abyss quest rewards | `test` | in progress — needs in-game check |
| 🟨 | Gomoku vs AI reward, pet release, gift-bag bulk open, lock gear | `test / captured` | in progress — needs in-game check |
| 🟨 | Multiplayer: other players in the same scene, movement, emotes, group emotes, chat (nearby, world, private), sitting | `test` | in progress — tested with 2 local clients; needs in-game check |
| 🟨 | Part-time tasks, Moon Points to Wish Stones (official step prices), co-op ticket refill (6 a day) | `captured` | in progress — Moon Points per activity: 5 / 25 as seen |
| 🟨 | Online Gomoku (2 players) | `captured` | in progress — reward amounts estimated |
| 🟨 | Photo wall (upload, browse, like, favourite, delete) | `retest` | in progress — pictures served back to the game (full and thumbnail); needs in-game check |
| 🟨 | Rankings: Abyss, Boss Rush (everyone on this server) | `test` | in progress |
| 🟨 | Restaurant mini-game (buy, merge, sell, serve, quests) | `captured` | in progress — built from the game tables; no official capture |
| 🟩 | Field gear drops follow world level (official WL 0-5 gold & Epic+ scaling) | `done` | done — official WL 0-5 gold (+0% to +125%) & Epic+ (+0% to +80%) scaling in packs/official/systems/world.json |
| 🟨 | Overfield Backup: background start, follows a Steam restart, log file | `test` | in progress — needs a live run |

**Quest steps with a rule:** 1,265 / 1,265 (`▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰` 100.0%)

![Rozefield progress chart](docs/progress.png)

_Updated 2026-11-28 by `py devtools/progress.py` from [docs/checklist.json](docs/checklist.json)._

## About

Rozefield preserves OverField: the archived client and a private server that runs it after the official shutdown.

- [Archive notes: client build, endpoints, protocol, captures](docs/ARCHIVE.md)
- [Server: setup, login window, backup / import, GM commands](server/README.md)
- [Host your own server](docs/HOSTING.md)
- [Checklist (plain)](docs/PROGRESS.md)

## New features & QOL added (Gameplay)

| Area | Feature / QOL | What it does |
|---|---|---|
| **Social** | No friend limit | Friend list cap removed on Rozefield. |
| **Content** | Global + CN merged & translated | CN-only tables, 1,120 CN assets, and English translations available in-game. |
| **Plaza** | 500,000 decor limit | Expanded garden plaza decoration limit to 500,000. |
| **Field Drops** | Direct-to-bag monster material drops | Field monster material drops go straight into your normal bag instead of waiting in temporary storage. |
| **Outfits & Dye** | Protected original dye slot (Slot 0) | Every outfit keeps Slot 0 for its original colors (selectable anytime, cannot be dyed over) with Slot 1 unlocked by default for custom dyeing. |
| **Co-op** | Minimum players reduced (3 → 2) | Pop Balloons and Aerial Adventure can start with 2 players instead of 3. |
| **Shops** | All Fishing Rods on Chang's Store | All 10 Fishing Rods moved from Sherry to Chang's Lifestyle Store with official currencies (unpriced rods in Feline Tokens to encourage co-op). |
| **New Players** | First recruit 100% guarantees Shiika | New accounts always receive Shiika (`102001`) on their first recruit, matching the prologue story. |
