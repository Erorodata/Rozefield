# Rozefield progress: 77.94%

![progress](progress.png)

_OverField preservation: run the game on your own server after the official one closes. Updated 2026-11-24; regenerate with `py server/tools/progress.py`._

## Preservation & archive (93.8%)

- [x] Global client backup (playable copy)
- [x] CN 1.1.12 client copy (source of CN content)
- [x] Protocol recovered: 154 proto files, 2,308 messages, 733 message ids
- [x] Official traffic captures (redacted copies in repo)
- [x] Archived account (Player) imported and playable
- [x] Public snapshot of 490 other players
- [~] Player backup tool RozefieldBackup.exe: built; first live run waits for the official server to come back
- [x] Import backup from the login window

## Server & connection (74.0%)

- [x] Dispatch, HTTPDNS and region info
- [x] Login window with account picker
- [x] Patch delivery through the game's own updater
- [~] Client requests with a server handler (46.86% 142/303)
- [~] Requests seen in real play that are handled (96.84% 92/95)
- [ ] Multiplayer (other players in scenes, co-op): phase 2

## Content (Global + CN) (87.5%)

- [x] CN-only table rows merged into Global data
- [x] CN-only assets ported through the updater (1,120)
- [x] CN-only text translated to English
- [~] English UI after the CN patch: fix shipped, needs an in-game check

## Gameplay (56.6%)

- [x] New account start, characters, team
- [x] Outfits, gear equip, weapon / armor enhance
- [~] Character level up, level break, star up, skill up: costs from the game tables; needs in-game check
- [~] Profile, outfit / gear presets, pets, visit a friend's garden: needs in-game check
- [x] Shops (Rhombite shop gives the item)
- [x] Food buffs and item use
- [x] Channels, scenes, fields, friends' gardens
- [~] Chat and GM console (no double text): needs in-game check
- [~] Umbrella / badge / tool appearance: needs in-game check
- [~] Garden plaza: lift, presets, 500,000 limit: needs in-game check
- [x] Recruit banners and pulls
- [!] Recruit result screen (animation, can't leave): needs the game's Player.log
- [~] Quest engine: main story, story rewards, daily, delegate
- [~] Quest steps with an event rule (97.71% 1,236/1,265)
- [~] Main story quests cleared by an automated new account (16.67% 108/648)
- [~] Achievements: view archived progress
- [~] Achievements: earn and claim: counted from play, claim + group rewards; needs in-game check
- [~] Dye: colorants not consumed yet
- [~] Scrap (disassemble)
- [~] Life skills: cooking, sewing, making, handicraft, fishing: recipes, success chance, levels, skills, handbook rewards; needs in-game check
- [~] Gathering tools (net, axe, hammer, gloves, bottle): gather rewards + tool progress; needs in-game check
- [~] Dungeons (story, resource), vitality, sweep, monster drops: rewards from the game tables; needs in-game check
- [ ] Field treasure chests (rewards are server-side, not in client data)
- [ ] Mini-games and co-op (game hall)
- [~] Perform (instruments, emotes)

Legend: `[x]` done, `[~]` in progress, `[!]` blocked, `[ ]` not yet.

Requests seen in play that still get an empty answer: `AbyssInfoReq`, `DailyTaskExchangeReq`, `MultipleActionAcceptReq`
