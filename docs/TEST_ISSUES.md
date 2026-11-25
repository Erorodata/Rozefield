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
| 4 | UID shown on screen stays the old one after Log Out and logging in as another account | — | — | Open |

## Plaza

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 5 | Plaza stops loading when it has placed characters | Placed-character outfits were missing dye schemes and hidden parts, so the game failed to read them | Outfits sent in the official format | Fixed |
| 6 | Character placed on furniture: "Placement successful" but the character never appears; removing one leaves it standing | Official sends `GardenPlaceCharacterNotice` (to everyone in the plaza) before the reply; Rozefield only replied | Notice sent on place and remove | Fixed, retest |
| 7 | Decoration count in the decoration list moves by 2 per piece (placing or putting away) | The game counts pieces itself when one is taken in hand or put away; Rozefield also sent `FurnitureItemChangeNotice`, which official never sends for this | Notice removed; place and put-away now send the official update/remove notices | Fixed, retest |
| 8 | Public channel (e.g. channel 1) still shows the decorations of the plaza you came from | A public channel had no garden data, so the game kept the last plaza's furniture; official sends an empty garden | Empty garden sent for public channels | Fixed, retest |
| 9 | Seasonal plaza stage (event lawn, Ferris wheel, balloons, Halloween stage) could appear | The game picks the stage by date from the `SceneTheme` table | Event rows have no dates in Rozefield's config, so the default stage always shows | Fixed, retest |
| 10 | Furniture instrument: Play button missing | `ChangeMusicalItemRsp` returned item id 0 for a furniture instrument | Returns the furniture's item id | Fixed, retest |
| 11 | Changing channel keeps the same position; channel cannot be changed in some cases | — | — | Open |
| 12 | Chat messages are not kept | — | — | Open |

## Fields and life skills

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 13 | Field and Sequence entry point is random on every visit | No fixed entry point | Travel to a map without a target puts you at the map's official entry point; leaving a dungeon returns you to where you entered | Fixed, retest |
| 14 | Gathering (flowers, wood, stone, insects, water) ignores daily limits and lucky gathers | Limits were not tracked | Daily limits from `GatherRule`, lucky gathers, field hauls kept in the temporary bag until you return to the plaza | Fixed |
| 15 | Connection ends about 24 s after entering one Sequence dungeon | Not known yet | — | Open |

## Story and quests

| # | Issue | Cause | Fix | Status |
|---|---|---|---|---|
| 16 | Talk option does nothing; step stays 0/1 | The game reports the step by its scene resource id | Step accepted by resource id | Fixed |
| 17 | Dialogue plays and starts over | At the end of a dialogue the game reports the step by its own condition id | Step accepted by condition id | Fixed |
| 18 | Story "Claim reward": no popup, claimed only after reopening | Reply carried the story id, which is not in the quest table | Reply carries the story's last quest | Fixed |
| 19 | Story step "Eliminate Ashen Creatures": battle marker missing on the map, story does not continue | Story battle markers were never sent | Markers for story battles show while that step is in progress and update live | Fixed, retest |

All storylines still need a full pass; see [STORY_CHECKLIST.md](STORY_CHECKLIST.md).
