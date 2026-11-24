# OverField — Preservation Archive


Archived 2026-11-23 (shutdown period). Source: `H:\Backup\OverField` (a copy of the Steam install at `H:\SteamLibrary\steamapps\common\OverField`).

## 1. Client build

| Item | Value |
|---|---|
| Developer / product (app.info) | Inutan / OverField |
| Engine | Unity, IL2CPP (`GameAssembly.dll` 139.7 MB + `il2cpp_data/`) |
| Executable | `launcher.exe` (Unity player, *not* a separate launcher) |
| Client build (`version`) | 2026-10-24-12-00-58 |
| Newest resource manifest (YooAsset) | **2026-11-23-15-53-19** (patch pushed on shutdown day; replaced one 7 KB bundle `381647ed…` with `b98e8287…`; copied into the backup, old bundle and the 2026-11-09 `.version` kept) |
| Older manifests kept | 2026-10-24-12-00-58, 2026-11-04-17-16-53, 2026-11-09-11-50-10 |
| Asset system | YooAsset `DefaultPackage` (StreamingAssets/yoo = built-in, yoo/DefaultPackage/CacheFiles = hot-updated, 256 hash buckets 00–ff) |
| Scripting / hotfix | xLua (`xlua.dll`) + IFix (`IFix.Core.dll`) — patches arrive via the asset bundles |
| Main data | `launcher_Data/data.unity3d` (91.4 MB) |
| Protection | `FairGuardProtect.dll` (anti-tamper/anti-cheat) |
| Crash reporting | `CrashSight64.dll`, `UnityCrashHandler64.exe` |
| Analytics | ThinkingSDK / ThinkingAnalytics |
| Storage SDK | `Aliyun.OSS.dll` (Alibaba Cloud OSS — likely the CDN for hot-update bundles) |
| HTTP stack | Best.HTTP (`com.Tivadar.Best.HTTP.dll`), UnityWebRequest |
| Serialization | Newtonsoft.Json, LitJSON, Snappier (Snappy compression) |
| Platform | Steamworks.NET (`steam_api64.dll`) |
| Login SDK | QuickSDK PC (`Plugins/Win/PCSDK_release/PCSDKUI.exe`, Qt5 WebEngine) |
| Total entries | ~9,800 files under `StreamingAssets/yoo` alone |

## 2. Server endpoints found in the client

| Purpose | Endpoint | Source |
|---|---|---|
| Game server (remote) | `139.196.33.142` (port unknown — record with capture script) | `StreamingAssets/Config.txt` `RemoteServerIP` |
| Dev/local server (unused) | `127.0.0.1` | `Config.txt` `LocalServerIP`, `UseLocalServer = FALSE` |
| Account SDK base | `https://sdkapi-of-global.inutan.com` | `Quicksdk/qgpc_log.txt` |
| OAuth login page | `/openapi/oauth?openId=pcsdk&productCode=…&channelCode=default&theme=en&lang=en&sign=` | log |
| Login callbacks | `/loginSuccess.html`, `/loginCancel.html` | log |
| SDK product code | `14893566846394405145332210454456`, channel `default` | log |

**Useful for server recreation:** `Config.txt` has a `UseCustomConfig` / `UseLocalServer` / `LocalServerIP` switch, which may let the client skip the live discovery chain in section 2b. This is untested: the live session ignored `139.196.33.142` and found its servers through dispatch. The fallback is to redirect `dsp-global-of.inutan.com` and the two hard-coded dispatch IPs (via the hosts file or a local DNS) to a replacement server. The file must stay UTF-8, per its own header note.

## 2b. Live server map (captured 2026-11-23, session 16:20–16:46 MYT)

The `139.196.33.142` address in `Config.txt` was **not** used by the live game. The client discovers its servers at runtime through this chain:

| # | Step (client log name) | Endpoint | Protocol | Response captured |
|---|---|---|---|---|
| 1 | `GetLoginUrlList` | `8.134.240.36:80` | plain HTTP | ✅ (empty body, so the client falls back) |
| 2 | `RequestFallBackLoginServer` | `http://150.5.132.155:18881` | plain HTTP | ✅ |
| 3 | `SyncGMConfig` | `http://dsp-global-of.inutan.com:18881/dispatch/client_hot_update` | plain HTTP | ✅ full JSON (below) |
| 4 | Hot-update content | `https://d2b0sg4npngm2p.cloudfront.net/Resources` (fallback: `http://cdn-of-global.inutan.com/Resources`) — CloudFront `13.35.202.105`, `65.8.76.45`, `65.8.76.99` | HTTPS | Manifests + bundles already in `yoo/` (client said "Not found any download files", so the cache was complete) |
| 5 | `RequestRegionInfo` | via dispatch server | plain HTTP | ✅ full JSON (below) |
| 6 | Login SDK | `sdkapi-of-global.inutan.com` = `43.167.182.21:443` (+ Facebook login `2a03:2880:…:443`) | HTTPS | Message format only (section 3) |
| 7 | **Game gateway** | `150.5.131.114:11001` | raw TCP | ⏳ in pcap (probably encrypted) |
| 8 | Client log upload | `150.5.131.114:21001` | raw TCP | ⏳ in pcap |
| 9 | Payment callback | `http://150.5.131.114:19701/pay/v1/pay/quickGlobal/sendGoods` | plain HTTP | URL only |
| 10 | Other | `43.167.153.142:443` (Tencent Cloud, unidentified), `te-receiver-aws.thinkingdata.jp` (analytics), `jp-global-photo-prod.inutan.com` (photo sharing) | HTTPS | Not needed to run the game |

**SyncGMConfig response** (player IP removed):
```json
{"status":true,"message":"success",
 "hotOssUrl":"https://d2b0sg4npngm2p.cloudfront.net/Resources;http://cdn-of-global.inutan.com/Resources",
 "currentVersion":"2026-10-24-12-00-58_2026-11-09-11-50-10","server":"jp_global_prod",
 "ssAppId":"3e9b196609224f889fbc769234200511","ssServerUrl":"https://te-receiver-aws.thinkingdata.jp",
 "open_gm":false,"open_error_log":false,"open_netConnecting_log":false,"ipAddress":"<PLAYER_IP>",
 "payUrl":"http://150.5.131.114:19701","isTestServer":false,"error_log_level":2,
 "server_id":"31000","open_cs":false,"serverTime":1795422008072}
```
Request parameters: `version=2026-10-24-12-00-58`, `version2=ef00bcd296e82ea4ebeeced2acc8d6e0` (buildGUID), `accountType=16666` (Steam channel), `os=0`, `lastloginsdkuid`. Client app version 1.0.9.

**RequestRegionInfo response:**
```json
{"status":true,"message":"success","gate_tcp_ip":"150.5.131.114","gate_tcp_port":11001,
 "is_server_open":true,"text":"","client_log_tcp_ip":"150.5.131.114","client_log_tcp_port":21001,
 "currentVersion":"2026-10-24-12-00-58_2026-11-09-11-50-10",
 "photo_share_cdn_url":"https://jp-global-photo-prod.inutan.com/jp_global_prod"}
```

**What this means for a rebuilt server:** steps 1–5 are plain HTTP and their exact responses are above. A replacement only needs to answer them and send `gate_tcp_ip` to its own gateway. The flags `open_gm`, `open_error_log` and `open_netConnecting_log` are switched on by the server, so a replacement can set them to `true` to make the client log much more, probably including network messages. `is_server_open:false` + `text` is likely how the "server closed" notice is shown. The remaining unknown is the gateway TCP protocol on port 11001.

## 2c. Capture sessions

| Session | Folder | Time (MYT) | pcap | What was opened |
|---|---|---|---|---|
| 1 | `capture_20261123_161336` | 16:20–16:46 | 3.8 GB (whole PC) | Login, world, lobby, gacha, shop, mail, friends, character, pets, Battle Pass, Abyss, missions, achievements, photo wall, Blessing Tree, settings, channel switching |
| 2 | `capture_20261123_170423` | 17:09–17:56 (game started twice) | 224 MB | Weapon/armor/imprint star-up, scrapping a module, inventory, imprint collection, F1 missions + stamina refill, F2 quests (all tabs), F3 recruit (4 banners, rates, history pages 1–4), F4 fitting room (outfit change saved), F5 Laplace Tree (all tabs), events (7-day sign-in, Daily Dessert, announcements, gashapon + rates), Pass (quest + level reward claims), Life Skills (all 4), Investigate (started 1, Gap, friend list), Game Room, Perform (instrument + sheet music), team formation, camera + share, Unstuck, Pet (codex/storage/bag), decoration edit mode, Salvager list + character gear, chat tabs, group Interaction (by the player) |

| 3 | `capture_20261123_180325` | 18:07–18:22 | 254 MB | Movement (WASD, jump, double jump, umbrella glide off a cliff), sticker emote, Kirakira action, **Group High Five with another player**, dice prop roll, fishing rod and **vehicle** (Spiked Pufferfish Bumper) equip/drive/unequip, Friends → player profile / **Enter Home** / **Teleport**, chair interaction (server replied "All seats taken"), channel menu → Hot Channel → back to own garden |
| 4 | `capture_20261123_182705` | 18:33–19:13 | 149 MB | Settings (all 5 tabs incl. full key map), cooking/processing/weaving crafts, **NPC dialogues and commissions** (Evelyn, Zoe, Sherry: commission list/completed, **Oyster commission handed in** and next one accepted, Talk, Sip Coffee), **NPC shops** (Collection Shop with Feline Token, Cuisine Shop and Variety Store with gold; Daily Sidelines buy-back), main Shop (all 9 tabs), **real-money purchase attempts → server "Currently unavailable."**, Recruit Trial (Molly) combat stage cleared 9/9 incl. boss, stage exit via windmill |
| 5 | `capture_20261123_211935` | 21:19–22:14 (same game run as session 4) | 143 MB | Played by the player: **busy public channel 62 packed with players** during the shutdown period (crowd sync, world boss "Kraken" fight with many players), **character banner pulls (gacha)**, fishing, character screen, more NPC tasks |
| 6 | `capture_20261123_222021` | 22:20–23:24 (same game run as 4–5) | — | Yuzuki/Thera (commission, Ornament + Decoration shop, Talk), decoration placed in own garden (placement-cap and out-of-bounds checks), Chandler/Chang Taishi (commission, Luncheonette shop, **working Daily Sidelines buy-back**, Talk), **fishing** (setup, auto-catch ×3), Richard (tailor: Change Costume → Design Fitting Room, **Garment Dyeing**, Lyrical Clothing Store), ROTA building: Fantine (receptionist, Material Shop, Special Recruitment) and Irene, CLIFFS path to the clifftop lookout, bench/swing seating with Place/Recall Character |

All six sessions hit the same server chain as section 2b, and the dispatch responses were identical. Not captured: Boss Rush, actually catching a fish, detector/area devices, NPC dialogue/commission hand-in, mini-games (the mini-game list was empty), joining a co-op match, creating a new character.

**Channels and gardens** (as described by the player, and seen in the session):
- The world is split into numbered **channels**, shown in the bottom bar as `Channel: <number>`.
- The in-game "Switch to World Channel" screen states the rule: **"Please enter a channel ID between 1-99999 or above 1,000,000."** **1–99999** are public channels with no owner, run by the developers (the plaza was on a 4-digit one; named public channels such as 39, 2333 and 404 are featured). **1,000,000 and above** are player gardens. **Confirmed in session 3:** your own garden's channel equals your UID, and "Enter Home" on a friend took the player to channel = that friend's UID (matching the UID on their profile).
- The channel screen also has: manual channel ID entry, **Hot Channel** ("Try joining the most active channel now?", which landed in a busy player garden), **Last Joined Channel**, **My Channel** (go home), and a row of featured gardens.
- Garden plazas show a like counter and are titled "<owner>'s Garden Plaza".
- Each player has their own **garden**, a personal space they can decorate. You can switch between your own garden and other players' gardens.
- **A garden's channel number is the owning player's UID** (the UID shown bottom-left in the HUD). In session 2 the player was in another player's garden, and its channel number was that player's UID; the plaza showed `<owner>'s Garden Plaza` with a like counter.
- **Decoration rules:**
  - *In another player's garden* you can place **1 decoration** temporarily. Placing a different one takes back the one already placed, and it's retrieved automatically when you leave the channel. The edit-mode screen says: "Only 1 decoration can be temporarily placed in the current channel" / "Decorations will be automatically retrieved when leaving the channel."
  - *In your own garden* you can place as many decorations as you like, up to a placement cap (exact cap not recorded).
  - Edit mode has Lift, Lift Remotely, Retrieve and Decorations (theme picker with per-theme owned/total counts, e.g. "All Skins 197/370").
- Switching logs `OnChannelJumpCallback | 切换场景频道` (18 times across the two sessions), but the log doesn't print channel numbers. They're only in the gateway traffic.
- The in-game UID (HUD) is a different number from the internal account ID the client logs (`#account_id`, the `Save/Mobile/<id>` folders). A rebuilt server needs both, plus a mapping between them.

**Movement and social features** (session 3):
- **Movement:** WASD walk, Space jump, Space again in the air for a double jump; jumping off a ledge and pressing Space in the air opens an **umbrella glide**. While falling or gliding, a **Backtrack** button appears ("Tap [Backtrack] to return to your position 3 seconds ago").
- **Interaction panel** tabs: *Emotes* (stickers, shown above the head and posted to Nearby chat), *Actions* (solo animations such as Kirakira, Ta-da!, Peekaboo!), *Interaction* (consumable props with counts: dice, campfire, paper plane, fireworks and others; used from a "Select Item to Use" list by clicking the item's name), *Group* (two-player actions such as High Five, Handshake, Hug, Rub Cheeks and Spin Together; several are gated by friend intimacy, e.g. Hug I at 100 and Rub Cheeks II at 800), *Catcher* (traps for Ashen creatures).
- **Group actions:** the starter's request shows as a button over their head that other players can see; when another player presses it, both play the animation together.
- **Tools row:** Bare Hands, Fishing Rod, Bug Net, Logging Axe, Mining Hammer, Gathering Gloves, Water Bottle, Vehicle. Equipping one shows "Gear [<name>] equipped." and an Unequip button. The vehicle is a driveable mount.
- **Furniture:** seats show an interaction prompt; the server rejects taken seats ("All seats taken.").
- **Friends:** a card per friend with View Details (player profile: UID, level, birthday, status, skins, creation date, likes), Private Chat, Gift (intimacy gifts, with a daily limit and intimacy tiers), Bond Tags, Edit Note, Enter Home ("Enter the player's Home Channel?"), Teleport ("Teleport next to your friend?"), Delete Friend, Block, Report. The roster counter showed "201/200" (cap 200, apparently exceeded).

Client shortcuts found: **Esc** opens the phone menu, **F1** missions (Handbook), **F2** quests, **F3** recruit, **F4** fitting room, **F5** Laplace Tree, **Enter** chat. Hold **Alt** to show the cursor for HUD buttons. All lists scroll by click-and-drag (touch-style UI).

## 2d. Gacha rules (from the in-game info pages, 2026-11-23)

**Limited Salvager recruitment, "Detective of the City of Fog" (SSR Molly)**
- Every 10-pull guarantees at least 1 SR Salvager.
- Each SSR Salvager has a 50% chance to be the limited one; the limited one is guaranteed within 70 pulls; the pity counter resets when it's obtained.
- Single pulls count toward pity. Pity is shared across all Limited-Time banners and separate from Regular Recruitment.
- Special Commemorative Footage from clearing the Main Story is added to the pool automatically. Story Footage only enters the pool after the related story is cleared.

| Tier | Rate | Pool |
|---|---|---|
| SSR Salvager | 1.00% (2.1% with pity) | Lexy, Flavoure, Momoko, Nicy, Miao, Lynn, Cho, Molly |
| SR Salvager | 6.00% | Fei, Shiika, Tutu, Cacao, Kobushi, Dove |
| SSR Footage | 0.80% | Miao and Meow, Aftertaste, The Locked Room, An Unexpected Call, Gathering Lotus, Rose Garden, Catch the Breeze, Interrogation Record, Stairway of Time, Field Corridor, Clocktower Library, Wheel of Time, Cherry-Blossom Fantasy, Melody of Peace, The Tiger's New Robes, Reflected in Her Eyes, Snack Street, Naoki's Joy, The Witch's Break, Anime Protagonist, Magic Spin-Spin-Spin, Star, Sound Wave, Unstable, Dreamscape, Halloween Candy Dream |
| SR Footage | 92.20% | Cacao's Day Off, Today's Look, Warm Winter Morning Tea, Day Off, The Clock Tower, Ski Training, Idol SHOW, The Next Stop, Field, Fast-Food Time, Path in a Bottle, Taking Shape, Poolside Holiday, Reading Nook, Polar Photoshoot, Floating, At the Café, Latte Art, The City from Above, Reverie, Seaside Holiday, Time to Fight, Into the Wild, Momo's Day Off, Welcome, Daisies, Night Patrol, Fitting Room, Rest in the Shade, Mirror World, Lolomay's Gift, A Child's Game, Farewell Witch, A Song for You All, Listen to Our Song, A Wish as Bright as a Star |

Other banners: Cowgirl Witch (rerun, SSR Millia, displayed adventurer guaranteed in 70 pulls), Regular Recruitment, Rota Featured. Recruitment history is paged (122 pages for this account, server time).

**Constellation Gashapon Machine, "Orison Sprite" (ends 2026-12-09 23:59:59)**
- 1 Gacha Coin per draw; the first single draw is 10% off.
- A finite box: 15 item types, 120 pieces in total (5 themed + 10 regular). Each draw removes that piece; when a count hits 0 it can't be drawn again.
- When all themed items are drawn, the remaining items are given as rewards. If the box or themed items run out during a 10-draw, unused coins are refunded. Unused coins carry over to future machines.

| Item | Initial rate |
|---|---|
| Star Wish Sprite veil, long hair, Stella Wisp Dress, Starlight Sprite Crystal Feather, Star Wish Sprite Mask (x1 each) | 1.5% each |
| Star Wish Sprite Left Wing, Right Wing (x1 each) | 3% each |
| Stellar Wish Avatar Frame, Exclusive Ticket, Common Ticket (x1 each) | 3.5% each |
| Starstones x60, Wish Stone x2 | 12% each |
| Gold x10000 | 16% |
| Heartfelt Chocolate x1, Dye x1 | 18% each |

## 3. Login SDK protocol (from qgpc_log.txt, Apr 14 – Nov 23 2026)

The game talks to `PCSDKUI.exe` over a named pipe. Messages observed:

| Direction | Message | Count | Payload fields |
|---|---|---|---|
| game → SDK | `gameName‖qgpc&action‖callLogin&url‖<base64 OAuth URL>&width‖470&height‖475…` | 281 | window geometry, lang, base64 URL |
| SDK → game | `{"action":"init","params":{}}` | 287 | — |
| SDK → game | `{"action":"loginSuccess","params":{…}}` | 278 | `authToken`, `userToken`, `uid`, `username`, `timeleft` (`"-1"`) |
| SDK → game | `{"action":"loginCancel"}` | 6 | — |
| SDK server reply | `updateRole Success: {"status":true,"data":null,"message":"role up success"}` | 296 | `status`, `data`, `message` |

Tokens are encoded as `@NNN@NNN@…` byte strings. A recreated server only needs to accept whatever token the stub SDK hands the game, so a fake SDK that returns `loginSuccess` with any values should get past login.

## 4. What's preserved vs. what isn't

| Preserved | Status |
|---|---|
| Full client binaries + IL2CPP metadata | ✅ in this folder |
| All three resource manifests + cached hot-update bundles (latest 2026-11-09) | ✅ |
| Server address / config switch | ✅ (`Config.txt`) |
| Login SDK message format | ✅ (redacted log: `qgpc_log_REDACTED.txt`) |
| Hash manifest of every file (10,773 files; the backup is identical to the Steam install) | ✅ `capture_20261123_161336/hashes*.csv` |
| Live game-server traffic (pcap) | ✅ sessions 1–5 (3.8 GB, 224 MB, 254 MB, 149 MB, 143 MB), see section 2c |
| Gacha rules and rate tables | ✅ section 2d |
| Server chain, ports and dispatch responses | ✅ section 2b, `game_connections.csv` |
| Client logs, 16–23 Nov (14 sessions) + Player.log | ✅ raw in the capture folder; redacted copies in `shareable_logs/` |
| Gateway protocol (port 11001) decoded | ✅ plaintext protobuf, 733 ids, full schemas — see `server/` |
| Server-side logic (gacha rates, battle validation, DB) | ❌ never on the client; must be reconstructed from traffic + client data tables |

## 5. Capture tips (while servers are still up)

- Run `OverField_Capture.ps1` as Administrator, start the game from Steam, press **Q** in the script window after quitting.
- Touch as many systems as possible: login, lobby, every menu, story chapter, battle, gacha banner view (and a pull if you have currency), mail, shop, events, friends, settings, logout. Each screen is a new request type for whoever rebuilds the server.
- Do 2–3 separate sessions; repeated login sequences help separate fixed fields from per-session ones.
- Traffic will be encrypted (TLS for the SDK, likely custom encryption for the game socket). The pcap still records message sizes, order and timing; decrypting it needs the keys from the client (`GameAssembly.dll` + `global-metadata.dat`), which is the reverse-engineering step for the revival team.

## 6. Privacy — read before sharing

- The **original** `launcher_Data/Quicksdk/qgpc_log.txt` holds your account uid, username and login tokens. Share only `qgpc_log_REDACTED.txt`.
- `capture.pcapng` and the copied client logs will also contain your session data. Keep the raw copies private; share redacted copies or hand them only to people you trust.
- The raw `ClientLog/*.txt`, `Player.log` and `outLog.txt` contain your **login email**, tokens, account IDs, IP and device IDs. `shareable_logs/` has the same logs with all of these replaced by `<EMAIL>`, `<TOKEN>`, `<ACCOUNT_ID>` and similar tags; `_dispatch_responses.json` there collects every distinct server response found in the logs.
- `capture.pcapng` holds *all* traffic from your PC during the session, not just the game. Before sharing it, slim it in Wireshark: apply the display filter `ip.addr==150.5.131.114 || ip.addr==150.5.132.155 || ip.addr==8.134.240.36`, then use File → Export Specified Packets → "All displayed". The result has only the game-server traffic, and should be a few MB instead of 3.8 GB. It still contains your session, so share it only with trusted people.
- `capture.etl` (2.8 GB) is the raw source of the pcapng and can be deleted.
- `Plugins/Win/PCSDK_release/cache/` (Cookies etc.) is a browser profile for the login window — exclude it from any public upload.


## 7. Service history

- Oct 2024: launched in Japan under NetEase Games. NetEase ended service on 17 Feb 2025 11:59 JST and operating rights returned to the developer.
- 6 Nov 2025: relaunched by INUTAN / Ekoneko Studio (PC, iOS, Android), developer-operated. **This archive is of the developer-operated service** (server `jp_global_prod`, server_id 31000).
- Nov 2026: second end-of-service notice; captures taken 2026-11-23 before shutdown (exact shutdown date not recorded here).

## 8. Garden NPC directory (Rota Garden Plaza)

| NPC (commission name) | Location | Options | Shop currency |
|---|---|---|---|
| Evelyn | Café terrace by the pumpkin | Recruit, Commission, Shop, Talk | Feline Token |
| Zoe | Café counter | Commission, Shop, Sip Coffee, Talk | Gold |
| Sherry | General Store, across the fountain from the café | Commission, Shop, Talk | Gold (+ Starstone items) |
| Thera / Yuzuki | Ornament shop next to Sherry | Commission, Shop (Ornament + Decoration), Talk | Feline Token |
| Chandler / Chang Taishi | Beach shack (jump the terrace railing) | Commission, Shop (Luncheonette), Talk | Gold |
| Richard | Tailor shop next to the café | Change Costume, Commission, Shop (Textile/Dye/Sidelines), Talk | Gold, Feline Token |
| Fantine | ROTA building reception, next to the tailor | Commission, Shop (Material, Special Recruitment), Talk | Gold, recruit ticket |
| Irene | ROTA building lobby | Talk | — |

Daily Sidelines buy-back only succeeds when the item price shows **blue** (player owns the item); a **red** price silently does nothing. Many NPCs have two names (shop sign vs commission panel).
