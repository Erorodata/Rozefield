# Content pack templates

Copy `my_story` to `Server\packs\<your pack name>` and edit. Restart the server (or Push update) to load it.

| File | What it is |
|---|---|
| `pack.json` | Name, version, author, load `order` (higher loads later and wins), `enabled` |
| `story/*.json` | A chapter and its stories (each story starts at its `first_quest`) |
| `quests/*.json` | Quests and their steps |
| `npcs/*.json` | NPCs: name, title, functions (`talk`, `shop`, `quest_board`, `commission`), talk dialogues, shops |
| `dialogue/*.json` | Conversations: lines with speaker and text, optional choices with `goto` |
| `areas/*.json` | Field areas: NPC spots, monster spawns, chests, triggers, entry point (used by Overfield Builder) |
| `systems/*.json` | Rules; only the keys you write change (see `packs/official/systems`) |
| `tables/<table>.json` | Anything else, straight into a game table by ID |

Quest step `do` values: talk, kill, collect, have, go_scene, unlock_area, open_box, mechanism, dungeon, encounter,
level, emote, eat, cook, or `raw` with `condition` (EAchieveCondition name) and `param`.

Text: a plain string, or `{"en": "...", "cn": "...", "tc": "...", "ja": "...", "ko": "..."}` (missing languages use English).

Ids: use your own range (for example 900000+) so you never collide with official content. Changing an official row
needs `"override": true`. Problems are written to the server log as `[packs]` lines.

New dialogue, NPC spots and areas show in game once Overfield Builder builds the client bundles for the pack.
