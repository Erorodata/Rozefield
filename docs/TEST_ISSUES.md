# Play-test issues

Issues found by playing an archived account on Rozefield and comparing with the official game (live until 8 Feb 2027).
Player names and IDs are left out on purpose.

Status: **Fixed** = fixed and confirmed in game · **Fixed, retest** = fixed on the server, waiting for an in-game check ·
**Open** = known, not fixed yet.

## Login and account

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 1 | Settings → Log Out reconnects to the same account instead of the login screen | `PlayerOfflineRsp` had no reason | Reply with reason `LOGOUT`; the game then returns to the login screen | Fixed |
| 2 | After login the game stops loading part of the data (handbook, boss rush, manuals) | Login data was missing sub-messages the game reads one after another (`daily_task`, `player_buffs`, `questionnaire_info`, quest bonus fields); the first missing one stopped the chain | Login data always carries them | Fixed |
| 3 | First login places the player somewhere random | No fixed spawn | Login always puts the player at the official plaza spawn | Fixed |
| 4 | UID shown on screen stays the old one after Log Out and logging in as another account | — | Checked in game: the UID changes with the account | Fixed |

## Plaza

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 5 | Plaza stops loading when it has placed characters | Placed-character outfits were missing dye schemes and hidden parts, so the game failed to read them | Outfits sent in the official format | Fixed |
| 6 | Character placed on furniture: "Placement successful" but the character never appears; removing one leaves it standing | Official sends `GardenPlaceCharacterNotice` (to everyone in the plaza) before the reply; Rozefield only replied | Notice sent on place and remove | Fixed |
| 7 | Decoration count in the decoration list moves by 2 per piece (placing or putting away) | The game counts pieces itself when one is taken in hand or put away; Rozefield also sent `FurnitureItemChangeNotice`, which official never sends for this | Notice removed; place and put-away now send the official update/remove notices | Fixed |
| 8 | Public channel (e.g. channel 1) still shows the decorations of the plaza you came from | Two parts: a public channel had no garden data (the game kept the last plaza's furniture; official sends an empty garden), and the plaza scene itself carries a group of event furniture ("活动家具": Halloween trees, ghosts, pumpkins, cake world, voxel buildings) that shows on every channel | Empty garden sent for public channels; the event furniture group is switched off in the Rozefield patch | Fixed, retest |
| 9 | Seasonal plaza stage (event lawn, Ferris wheel, balloons, Halloween stage) could appear | The game picks the stage by date from the `SceneTheme` table | Event rows have no dates in Rozefield's config, so the default stage always shows | Fixed, retest |
| 10 | Furniture instrument: Play button missing | `ChangeMusicalItemRsp` returned item id 0 for a furniture instrument | Returns the furniture's item id | Fixed |
| 11 | Changing channel keeps the same position; channel cannot be changed in some cases | — | Checked in game: channel change works and keeps the position | Fixed |
| 12 | Chat messages are not kept | World chat was only in memory, channel (nearby) chat not kept at all, and entering a channel sent an empty history | World and channel chat saved to `save/chat.json` (last 50 lines each); entering a channel sends its history, as official | Fixed, retest |
| 20 | Building blocks (e.g. Black Blocks) cannot be bought: not in the shop | Shop slots told the game the slot number instead of the pool item's own index, so the game found no item (affected most shops); limits never reset | Official pool item index, multi-item slots pick one item per refresh, daily / weekly / monthly limits reset | Fixed, retest |
| 21 | Dye does not use up colorants | Not built | Each dye uses 1 of the chosen colorant, with a bag update, as official | Fixed, retest |
| 22 | Some quest steps never complete: spend gold / vitality / energy, pass a Sequence, like a garden, make a friend, use an interaction item | No rule for those step types | Counted from play (1,264 of 1,265 steps now have a rule) | Fixed, retest |
| 23 | Photo wall pictures never load (only titles) | The game downloads pictures from `<photo address>/<code>` and `/thumb/<code>`; Rozefield had no such address | Pictures served from `save/photos` | Fixed, retest |
| 24 | Field completion % ("Garden Realm completion reached 10%") never moves for new play | Field completion was only the archived official number | Counted from collectibles, battles, areas, challenges and riddles per map (matches official exactly on all 7 archived maps); the quest step follows it | Fixed, retest |
| 25 | Handbook/achievement screens don't change after claiming: treasure handbook, character achievements, world levels, Boss Rush, challenge friend ranks | Only the archived official answer was shown | Archived answer plus what you did on Rozefield | Fixed, retest |
| 26 | Wish list: friends can't gift items from it | Not built | Add/remove (30 max), friends see it per item, a friend buys it with in-game currency (3 a week) and you get it by mail | Fixed, retest |
| 27 | Friends on other PCs can't join | Every address the server gave out was this PC's own (127.0.0.1) | Each player gets the address they reached the server on; `setup_client.ps1 -ServerIP` sets up a friend's game | Fixed, needs a second PC |

## Fields and life skills

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 13 | Field and Sequence entry point is random on every visit | Rozefield placed the team at the spot where you stood outside; official sends each Sequence's own start point | Official start points for the Sequences recorded in captures (39), the game's own start point for the rest; plaza entered from elsewhere starts at the plaza spawn, plaza-to-plaza keeps your position, leaving a Sequence puts you back at its entrance | Fixed, retest |
| 14 | Gathering (flowers, wood, stone, insects, water) ignores daily limits and lucky gathers | Limits were not tracked | Daily limits from `GatherRule`, lucky gathers, field hauls kept in the temporary bag until you return to the plaza | Fixed |
| 15 | Game closes about 25 s after entering one Sequence dungeon (11106) | Not known yet | — | Open |

## Story and quests

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 16 | Talk option does nothing; step stays 0/1 | The game reports the step by its scene resource id | Step accepted by resource id | Fixed |
| 17 | Dialogue plays and starts over | At the end of a dialogue the game reports the step by its own condition id | Step accepted by condition id | Fixed |
| 18 | Story "Claim reward": no popup, claimed only after reopening | Reply carried the story id, which is not in the quest table | Reply carries the story's last quest | Fixed |
| 19 | Story step "Eliminate Ashen Creatures": battle marker missing on the map, story does not continue | Story battle markers were never sent | Markers for story battles show while that step is in progress and update live | Fixed |

All storylines still need a full pass; see [STORY_CHECKLIST.md](STORY_CHECKLIST.md).
Values still estimated (no official answer recorded) are listed in [OFFICIAL_CAPTURE_CHECKLIST.md](OFFICIAL_CAPTURE_CHECKLIST.md).
