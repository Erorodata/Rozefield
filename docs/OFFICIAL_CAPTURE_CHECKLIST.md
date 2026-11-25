# Official capture checklist (until 8 Feb 2027)

Some Rozefield values are estimates because no official answer was ever recorded. Each row below is one thing to do
on the **official** game while `OverField_Capture.ps1` records; the capture gives the exact official answer and the
estimate is replaced. Rules as always: no real money, no chat, no friend requests / reports / blocks, nothing sold or
deleted. In-game currency spent by the action itself is fine.

| # | On official, do | Records | Replaces (Rozefield) |
|---|---|---|---|
| 1 | Exploration: collect a finished send-out (and one team exploration) | `ExploreRewardReq` / `ExploreCollectRewardReq` | Exploration reward amounts |
| 2 | Join a friend's exploration break and collect it (if a friend has one) | `IntervalJoinReq`, `IntervalRewardReq`, `FriendIntervalInitRsp` | Friend exploration (not built: needs this answer) |
| 3 | Handbook → Posters: claim one poster illustration reward | `PosterIllustrationRewardReq` | Poster handbook reward |
| 4 | Handbook → Treasure: claim one reward of each kind (book, map, utensil, shovel) | `TreasureIllustrationRewardReq` | Treasure handbook rewards |
| 5 | Badges: open one page box, claim one page reward, one badge achievement | `AbilityBadgePageBoxActiveReq`, `AbilityBadgePageRewardReq`, `AbilityBadgeAchieveRewardReq` | Badge rewards |
| 6 | Clear a Sequence for stars, claim the star reward and the task reward | `DungeonStarRewardReq`, `DungeonTaskFinishRewardReq` | Sequence star / task rewards |
| 7 | Level up one field area | `AreaLevelUpReq` | Area level-up reward |
| 8 | Pick up field coins; dig one treasure spot; open one supply box | `CollectCoinReq`, `TreasureDigReq`, `SupplyBoxRewardReq` | Coin, dig and supply box amounts |
| 9 | Open field chests of each kind you meet (normal, riddle, challenge, encounter) | `TreasureBoxOpenReq` / `Rsp` | Field chest amounts |
| 10 | Defeat field monsters on 2 different world levels | `MonsterDeadRsp` drops | Gear drops by world level |
| 11 | Gomoku vs AI: one win and one loss; online Gomoku: one game (if someone is there) | `GomokuSinglePlayerRewardReq`, online result | Gomoku rewards |
| 12 | Claim every event reward that is open (gift, invite, recall, regular, quest, sandbag) | `Activity*RewardReq` / `Rsp` | Event reward amounts |
| 13 | Wishing tree: one wish; turn Moon Points into Wish Stones once | wishing tree / Moon Points answers | Wish Stone income |
| 14 | Do one of each Moon Points activity (gather, monster, chest, co-op, part-time task) | `PackNotice` after each | Moon Points per activity |
| 15 | Pop Balloons and Aerial Adventure: play 3 rounds each | room / layout notices | More co-op layouts |
| 16 | Restaurant mini-game: play one round (buy, merge, serve, a quest reward) | `RestaurantGame*` | Restaurant check against official |

When a capture is done, put the folder in `_archive` as usual and say which rows it covers.
