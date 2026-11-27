# Official capture checklist (until 8 Feb 2027)

Some Rozefield values are estimates because no official answer was ever recorded. Each row is one thing to do on the
**official** game while `OverField_Capture.ps1` records (it asks for administrator rights itself; without them the
capture is empty). Rules as always: no real money, no chat, no friend requests / reports / blocks, nothing sold or
deleted. In-game currency spent by the action itself is fine.

Status: **Captured** = the official answer is recorded · **Partly** = some of it · **Needed** = not recorded yet.

| # | On official, do | Records | Replaces (Rozefield) | Status |
|---|---|---|---|---|
| 1 | Astral Atlas: activate boxes not active yet | `AbilityBadgePageBoxActiveReq/Rsp` | What each box gives (estimate: Gold) | Partly: page 1 boxes 5, 24, 28, 29, 31, 34, 35, 38, 39, 40 & page 2 boxes 1, 4 known (2026-11-26 & 11-27) |
| 2 | Astral Atlas: claim a page reward | `AbilityBadgePageRewardReq` | Page reward | Needed |
| 3 | Astral Atlas: claim an Atlas achievement reward | `AbilityBadgeAchieveRewardReq` | Achievement reward | **Captured**: 1 moonstone of that map per achievement |
| 4 | Level up one field area | `AreaLevelUpReq` | Area level-up reward | Needed |
| 5 | Exploration: send a team out, then collect it | `ExploreReq`, `ExploreRewardReq` / `ExploreCollectRewardReq` | Exploration reward amounts | Partly: send-out only |
| 6 | Exploration break (interval): start, then claim | `IntervalStartReq`, `IntervalRewardReq` | Interval reward | Needed |
| 7 | Join a friend's exploration break and collect it | `IntervalJoinReq`, `FriendIntervalInitRsp` | Friend exploration | Partly: `FriendIntervalInitRsp` captured (2026-11-27); `IntervalJoinReq` needed |
| 8 | Handbook → Posters: claim a poster illustration reward | `PosterIllustrationRewardReq` | Poster handbook reward | **Captured**: 10 Starstones |
| 9 | Handbook → Treasure: claim one of each kind | `TreasureIllustrationRewardReq` | Treasure handbook rewards | Needed |
| 10 | Clear a Sequence for stars; claim star and task rewards | `DungeonStarRewardReq`, `DungeonTaskFinishRewardReq` | Sequence star / task rewards | Partly: task rewards captured (`11110`, `21112`, `21120` match `RewardID`); star reward needed |
| 11 | Pick up field coins; dig a treasure spot; open a supply box | `CollectCoinReq`, `TreasureDigReq`, `SupplyBoxRewardReq` | Coin, dig, supply box amounts | Partly: coins (1 Yellow Star each) and supply box captured; digging needed |
| 12 | Open field chests of each kind (normal, riddle, challenge, encounter) | `TreasureBoxOpenReq`, `TreasureBoxPickupReq` | Field chest amounts | Partly: 297 opens + pickups |
| 13 | Defeat field monsters on 2 world levels | `MonsterDeadRsp` drops | Gear drops by world level | Partly: 216 kills / 58 drops captured (2026-11-27) |
| 14 | Gomoku vs AI: a win and a loss | `GomokuSinglePlayerRewardReq` | Gomoku AI reward | Needed |
| 15 | Online Gomoku: one game (needs a second player) | online result | Online Gomoku reward | Needed |
| 16 | Any mini-game reward screen | `GamePlayRewardReq` | Mini-game reward | Needed |
| 17 | Recruit: get an R and an SSR result | `GachaRsp` extras | Bonus items per result | Partly: SR and SSR captured (new and repeat, including repeat SSR imprint `111 x20 + 107 x500`); R not seen |
| 18 | Claim every open event reward (gift, invite, recall, regular, quest, sandbag) | `Activity*RewardReq/Rsp` | Event reward amounts | Partly: 7-day quests & regular event (`4008`) captured (table-driven); recall / sandbag needed |
| 19 | Event: hit the sandbag; Koi: use an item; upload a wish text | `ActivitySandbagHitReq`, `ActivityKoiUseItemReq`, `ActivityUploadWishTxtReq` | These are only acknowledged now | Needed |
| 20 | Wishing tree: one wish; Moon Points → Wish Stones once | wishing tree answers | Wish Stone income | Needed |
| 21 | One of each Moon Points activity (gather, monster, chest, co-op, part-time) | `PackNotice` after each | Moon Points per activity | Partly: 82 moon collects, 204 moon quest rewards |
| 22 | Pop Balloons and Aerial Adventure: 3 rounds each | room / layout notices | More co-op layouts | Partly: 6 rounds (2026-11-25 01:13) |
| 23 | Co-op team: invite a player, dismiss the team; beacon ready | `MPTeamInviteReq`, `MPTeamDismissReq`, `MPBeaconPlayerReadyReq` | Built from the game; check against official | Partly: mode change, member updates, beacon actions, `MPTeamDismissReq/Notice` captured (2026-11-27) |
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
| capture_20261126_214953 | 12,451 | Sequence Lakeheart Isle (11106) full run, dungeon chests, coins, dye, stamina potions, achievement rewards, photo wall |
| capture_20261123_161336 (game_only) | 8,639 | First official capture (none of the checklist rows) |
| capture_20261127_011540 / 021531 / 132600 / 140634 / 182218 / 183022 / 195529 / 195603 / 231120 | 190,315 | 7 more Atlas boxes (`1:28/29/35/39/40`, `2:1/4`), repeat SSR imprint (`111 x20`), `ActivityRegularReward` (`4008`), `DungeonTaskFinishReward` (`11110`/`21112`/`21120`), 216 `MonsterDead` kills, 213 field chests, `FriendIntervalInitRsp`, `MPTeamDismissNotice`, `MPTeamBeaconNotice`, `GetCollectMoonInfoRsp.emotionMoons`, Abyss quests, fishing, turntable |

When a capture is done, say which rows it covers.
