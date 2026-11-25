# Rozefield progress: 83.29%

![progress](progress.png)

_OverField preservation: run the game on your own server after the official one closes. Updated 2026-11-26; regenerate with `py server/tools/progress.py`._

## Preservation & archive (93.8%)

- [x] Global client backup (playable copy)
- [x] CN 1.1.12 client copy (source of CN content)
- [x] Protocol recovered: 154 proto files, 2,308 messages, 733 message ids
- [x] Official traffic captures (redacted copies in repo)
- [x] Archived account imported and playable
- [x] Public snapshot of 490 other players
- [~] Player backup tool Rozefield Backup.exe: built; first live run waits for the official server to come back
- [x] Import backup from the login window

## Server & connection (91.7%)

- [x] Dispatch, HTTPDNS and region info
- [x] Login window with account picker
- [x] Patch delivery through the game's own updater
- [x] Client requests with a server handler (100.00% 303/303)
- [x] Requests seen in real play that are handled (100.00% 140/140)
- [~] Online play: friends on other PCs (LAN / internet), per-player server address, friend setup script: needs a test with a second PC

## Content (Global + CN) (87.5%)

- [x] CN-only table rows merged into Global data
- [x] CN-only assets ported through the updater (1,120)
- [x] CN-only text translated to English
- [~] English UI after the CN patch: fix shipped, needs an in-game check

## Gameplay (60.2%)

- [x] New account start, characters, team
- [x] Outfits, gear equip, weapon / armor enhance
- [~] Character level up, level break, star up, skill up: costs from the game tables; needs in-game check
- [~] Profile, outfit / gear presets, pets, visit a friend's garden: needs in-game check
- [~] Shops: every shop item shows (pool item index as official), multi-item slots rotate, daily / weekly / monthly limits reset: needs in-game check
- [x] Food buffs and item use
- [x] Channels, scenes, fields, friends' gardens
- [~] Chat and GM console: world and channel history kept across logins and restarts: needs in-game check
- [~] Umbrella / badge / tool appearance: needs in-game check
- [~] Garden plaza: lift, presets, 500,000 limit: needs in-game check
- [x] Recruit banners and pulls
- [~] Recruit result screen (animation, can't leave): results now carry the official bonus items + quality; needs in-game check
- [~] Quest engine: main story, story rewards, daily, delegate
- [x] Quest steps with an event rule (100.00% 1,265/1,265)
- [x] Main story quests cleared by an automated new account (100.00% 648/648)
- [~] Achievements: view archived progress
- [~] Achievements: earn and claim: counted from play, claim + group rewards; needs in-game check
- [~] Dye: each dye uses 1 colorant as official; needs in-game check
- [~] Scrap (disassemble)
- [~] Life skills: cooking, sewing, making, handicraft, fishing: recipes, success chance, levels, skills, handbook rewards; needs in-game check
- [~] Gathering tools (net, axe, hammer, gloves, bottle): gather rewards + tool progress; needs in-game check
- [x] Dungeons (story, resource), vitality, sweep, monster drops: official flow from capture: final chest -> temp storage -> pickup; 38 dungeons' chest contents observed
- [~] Field treasure chests, encounters, riddles, challenges, moons: 1300 chest positions + your opened-chest state imported; encounter/dynamic chest per capture; field chest amounts approximated
- [~] Co-op games: Pop Balloons, Aerial Adventure (solo or with players on this server): from the 2026-11-25 capture; only 2 platform layouts + 1 balloon layout were seen; needs in-game check
- [~] Perform (instruments, emotes)
- [~] Events: Pass, Gashapon, 7-day sign-in (official flow): from the 2026-11-24 capture; needs in-game check
- [~] Wishing tree and Wish Stone exchange: from the capture; Wish Stone income is estimated
- [~] Abyss: info, teams, team switch, best time: from the capture
- [~] Group emotes, dice, friend gifts (friendship points): from the capture
- [~] Energy / vitality purchases (official prices): needs in-game check
- [~] Exploration (send a team out), team exploration: reward amounts estimated
- [~] Handbook, imprint, treasure, badge, character achievement rewards: table rewards where the game has them, else estimated
- [~] Field extras: coins, digging, supply box, campfire, sitting, clap, music notes: needs in-game check
- [x] Redemption codes (server owner sets them in save/codes.json)
- [~] Boss Rush (solo), Abyss quest rewards: needs in-game check
- [~] Gomoku vs AI reward, pet release, gift-bag bulk open, lock gear: needs in-game check
- [~] Multiplayer: other players in the same scene, movement, emotes, group emotes, chat (nearby, world, private), sitting: tested with 2 local clients; needs in-game check
- [~] Part-time tasks, Moon Points to Wish Stones (official step prices), co-op ticket refill (6 a day): Moon Points per activity: 5 / 25 as seen
- [~] Online Gomoku (2 players): reward amounts estimated
- [~] Photo wall (upload, browse, like, favourite, delete): pictures served back to the game (full and thumbnail); needs in-game check
- [~] Rankings: Abyss, Boss Rush (everyone on this server)
- [~] Restaurant mini-game (buy, merge, sell, serve, quests): built from the game tables; no official capture
- [~] Field gear drops follow world level, 3% rare top quality: estimate
- [~] Rozefield Backup: background start, follows a Steam restart, log file: needs a live run

Legend: `[x]` done, `[~]` in progress, `[!]` blocked, `[ ]` not yet.
