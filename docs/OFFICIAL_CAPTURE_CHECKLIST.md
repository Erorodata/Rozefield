# Official capture checklist (until 8 Feb 2027)

Some Rozefield values are estimates because no official answer was ever recorded. Each row is one thing to do on the
**official** game while `OverField_Capture.ps1` records (it asks for administrator rights itself; without them the
capture is empty). Rules as always: no real money, no chat, no friend requests / reports / blocks, nothing sold or
deleted. In-game currency spent by the action itself is fine.

Status: **Captured** = the official answer is recorded · **Partly** = some of it · **Needed** = not recorded yet.

| # | On official, do | Records | Replaces (Rozefield) | Status |
|---|---|---|---|---|
| 1 | Astral Atlas: activate boxes not active yet | `AbilityBadgePageBoxActiveReq/Rsp` | What each box gives (estimate: Gold) | Partly: page 1 boxes 5, 24, 31, 34, 38 known (2026-11-26 20:42) |
| 2 | Astral Atlas: claim a page reward | `AbilityBadgePageRewardReq` | Page reward | Needed |
| 3 | Astral Atlas: claim an Atlas achievement reward | `AbilityBadgeAchieveRewardReq` | Achievement reward | **Captured**: 1 moonstone of that map per achievement |
| 4 | Level up one field area | `AreaLevelUpReq` | Area level-up reward | Needed |
| 5 | Exploration: send a team out, then collect it | `ExploreReq`, `ExploreRewardReq` / `ExploreCollectRewardReq` | Exploration reward amounts | Partly: send-out only |
| 6 | Exploration break (interval): start, then claim | `IntervalStartReq`, `IntervalRewardReq` | Interval reward | Needed |
| 7 | Join a friend's exploration break and collect it | `IntervalJoinReq`, `FriendIntervalInitRsp` | Friend exploration (**not built**) | Needed |
| 8 | Handbook → Posters: claim a poster illustration reward | `PosterIllustrationRewardReq` | Poster handbook reward | **Captured**: 10 Starstones |
| 9 | Handbook → Treasure: claim one of each kind | `TreasureIllustrationRewardReq` | Treasure handbook rewards | Needed |
| 10 | Clear a Sequence for stars; claim star and task rewards | `DungeonStarRewardReq`, `DungeonTaskFinishRewardReq` | Sequence star / task rewards | Partly: 77 dungeon finishes + final chests, no star / task claim |
| 11 | Pick up field coins; dig a treasure spot; open a supply box | `CollectCoinReq`, `TreasureDigReq`, `SupplyBoxRewardReq` | Coin, dig, supply box amounts | Partly: supply box captured (1 Starstone, 40 Feline Tokens, 90 Gold, next in 10–30 min) |
| 12 | Open field chests of each kind (normal, riddle, challenge, encounter) | `TreasureBoxOpenReq`, `TreasureBoxPickupReq` | Field chest amounts | Partly: 84 opens + pickups |
| 13 | Defeat field monsters on 2 world levels | `MonsterDeadRsp` drops | Gear drops by world level | Needed |
| 14 | Gomoku vs AI: a win and a loss | `GomokuSinglePlayerRewardReq` | Gomoku AI reward | Needed |
| 15 | Online Gomoku: one game (needs a second player) | online result | Online Gomoku reward | Needed |
| 16 | Any mini-game reward screen | `GamePlayRewardReq` | Mini-game reward | Needed |
| 17 | Recruit: get an R and an SSR result | `GachaRsp` extras | Bonus items per result | Partly: SR and SSR captured (new and repeat); R not seen |
| 18 | Claim every open event reward (gift, invite, recall, regular, quest, sandbag) | `Activity*RewardReq/Rsp` | Event reward amounts | Partly: 7-day event quests captured (param = day; items from the table) |
| 19 | Event: hit the sandbag; Koi: use an item; upload a wish text | `ActivitySandbagHitReq`, `ActivityKoiUseItemReq`, `ActivityUploadWishTxtReq` | These are only acknowledged now | Needed |
| 20 | Wishing tree: one wish; Moon Points → Wish Stones once | wishing tree answers | Wish Stone income | Needed |
| 21 | One of each Moon Points activity (gather, monster, chest, co-op, part-time) | `PackNotice` after each | Moon Points per activity | Partly: 82 moon collects, 204 moon quest rewards |
| 22 | Pop Balloons and Aerial Adventure: 3 rounds each | room / layout notices | More co-op layouts | Partly: 6 rounds (2026-11-25 01:13) |
| 23 | Co-op team: invite a player, dismiss the team; beacon ready | `MPTeamInviteReq`, `MPTeamDismissReq`, `MPBeaconPlayerReadyReq` | Built from the game; check against official | Partly: mode change, member updates, beacon actions |
| 24 | Restaurant mini-game: one round (buy, merge, serve, quest reward) | `RestaurantGame*` | Built from the tables; check against official | Needed |
| 25 | Month card: claim the daily reward (only if the account already has one) | `MonthCardRewardReq` | Month card (**not built**) | Needed (maybe in the 2026-11-23 16:13 capture, not read yet) |
| 26 | Home: change the room decor | `SetRoomDecorReq` | Room decor (accepted, **not saved**) | Needed (maybe in the 2026-11-23 16:13 capture) |
| 27 | Place a moon spot; collect a voice region | `PlaceMoonSpotReq`, `CollectVoiceRegionReq` | Accepted only | Needed |
| 28 | Clap, pop an emoji, sit in a vehicle next to another player | `ClapReq`, `PopEmojiReq`, `SceneSitVehicleReq` + notices to others | Others don't see these yet | Needed |
| 29 | Photo share: buy an upload slot; copy an outfit dye | `PhotoSharePaymentAddUploadGridReq`, `PhotoShareCopyFashionDyeReq` | Accepted only | Needed |

## Captures read so far

| Capture (Tools folder) | Game messages | Notable content |
|---|---|---|
| capture_20261123_170423 / 180325 / 182705 / 211935 / 222021 | read | Login data, Atlas page state, field play, dungeons |
| capture_20261124_211602 | 0 | Empty |
| capture_20261124_212230 | 22,214 | Dungeons, field chests, moon collecting |
| capture_20261124_232305 (game_only) | 21,265 | Recruits (SR), Abyss teams, events |
| capture_20261125_011353 | 6,581 | Co-op rooms, beacon, team |
| capture_20261125_194939 | 7,889 | Field chests, moon collecting |
| capture_20261125_203025 | 390 | Login only |
| capture_20261126_204010 | 719 | Login, Atlas state (box 31 first) |
| capture_20261126_204253 (game_only) | 21,206 | Atlas boxes + achievements, poster handbook, supply box, 18 recruits, 7-day event quests, sweeps, scrap, character achievements, field chests |
| capture_20261123_161336 (game_only) | 8,639 | First official capture (none of the checklist rows) |

When a capture is done, say which rows it covers.
