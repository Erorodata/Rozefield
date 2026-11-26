# Change log

Newest first. One entry per build bundle (`rozefield_buildN.bundle`); keep this file updated with every change.

| Build | Date | Changes |
|---|---|---|
| 48 | 2026-11-26 | Story flow as official (issue 34): a new story starts only when the player presses "Accept Quest" on the story screen; untouched stories started by older builds are reset once |
| 47 | 2026-11-26 | Sequence hidden chest as official: opened once for good, shows as found on the map's dungeon list (`isOpenSecretBox`), openable after the run ends; the "final chest opened" notice only for resource dungeons (official never sends it in Sequences) |
| 46 | 2026-11-26 | Sequence fix (issue 15, Lakeheart Isle): dungeon entry lists its chests as official; chests along the way are separate from the final chest. Coins give 1 Yellow Star and are kept per dungeon / map; Stamina Potions restore 30 / 60 / 120 Stamina. Checked against the 21:49 capture: dye, colorants, shop buys, stamina potions, coins match official |
| 45 | 2026-11-26 | From the 2026-11-26 official capture: Atlas boxes 5/24/34/38, Atlas achievement reward (1 moonstone each), poster handbook reward (10 Starstones), supply box (1 Starstone, 40 Feline Tokens, 90 Gold), recruit bonus items for SR/SSR new and repeat (repeat salvager gives 3 fragments), 7-day event quest rewards from the table, sweep pays the dungeon's repeat-clear chest. Limited banners no longer give imprints 11210–11450 (official: 0 in 180 pulls; the standard banner does). New `devtools/compare_capture.py` replays a capture against Rozefield and lists differences |
| 44 | 2026-11-26 | Gameplay: rifts with friends (start, quick finish, friends join, captain / member Stamina from the table, 48 h to claim), moon spots shown to the whole channel, voice regions kept per map, room decor kept and shown to visitors, pop emoji / clap high five / vehicle seats seen by others, event sandbag hits and wish text kept. Capture script records only the game's ports; `extract_all.bat` cuts big captures down |
| 43 | 2026-11-26 | Docs: [NOT_BUILT.md](NOT_BUILT.md) (everything not built or estimated), capture checklist with what each capture already covers, issues 29–33, story check progress, this change log |
| 42 | 2026-11-26 | Double Jump tutorial fixed: Astral Atlas box costs its moonstone and pays its unlock (page 1 box 31 = Double Jump); "own item / level / map" quest steps re-checked after every action; repair at login for boxes activated on older builds; quest updates only sent on real changes; UTF-8 log; panel asks before stopping an older server copy holding the ports |
| 41 | 2026-11-26 | Content packs: rules that were written in the code moved to `server/packs/official/systems/*.json`; host packs (quests, story, NPCs, dialogue, areas, tables) merged into the game tables; templates in `server/packs/_templates`; packs sent with Push update |
| 40 | 2026-11-26 | Panel: Delete player (test accounts; save kept in `save/deleted`) and Assign ID (friends, requests and private chats follow) |
| 39 | 2026-11-26 | Panel stops a server left running from an earlier start (pid file); no second Start while one is starting |
| 38 | 2026-11-26 | Server starts even when the game started first: the link port serves HTTP and game connections itself |
| 37 | 2026-11-26 | Prologue: "Access Area Terminal" completes on any terminal visit; first recruit brings a new salvager |
| 36 | 2026-11-26 | playit.gg: tries both tunnel-create formats; warns about a UDP tunnel (the game needs TCP) |
| 35 | 2026-11-26 | Clean layout: `server/` holds only what runs; dev tools in `devtools/`; Backup app in `backup/`. Builds before this are in the git history |
