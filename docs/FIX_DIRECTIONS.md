# Rozefield Fix Directions & Design Notes (Builds 50–59)

This document explains the architectural direction, reasoning, and technical choices behind the fixes and gameplay features added in **Builds 50–59**, so future maintainers and AI sessions (including Claude) have clear context on *why* each change was made this way.

---

## 1. Guiding Principles
- **Priority order:** `Gameplay > Server > Builder` (GitHub Releases held until testing reaches 100%).
- **Fix the whole class of a bug:** Prefer table-driven or systemic fixes in `server/packs/official/systems/*.json` and reusable tooling over one-off hardcodes.
- **Official-first with intentional QOL:** Match official captures and `GlobalConfig` tables by default, while keeping approved QOL improvements clearly documented.
- **Zero impact on official installs:** Client resource patches and IL2CPP plugins target only the Rozefield client copy — never Steam or Bilibili installations.

---

## 2. Capture & Play-Test Fixes (Builds 50–53)
- **Official 2026-11-27 captures (~190k messages, Build 50):**
  - Added 7 Astral Atlas boxes (`1:28/29/35/39/40`, `2:1/4`) to `packs/official/systems/atlas.json`.
  - Fixed repeat SSR imprint bonus (`111 x20 + 107 x500`), table-driven `ActivityRegularRewardReq` / `ActivityInviteRewardClaimReq` / `ActivityGiftRewardReq`, `DungeonViewReq.taskDataLst`, `MPTeamDismissNotice` / `MPTeamBeaconNotice`, `CollectMoonReq` (no extra `DailyTaskUpdateNotice`), `GetCollectMoonInfoReq.emotionMoons`, `ChangeNickNameReq.items`, and `GetArchiveInfoReq.value`.
  - *Intentional QOL kept:* Field monster material drops remain direct-to-bag.
- **Live Play-Test Fixes (Builds 51–52):**
  - **New salvagers & outfits (`player.py`):** Newly pulled salvagers and their default outfits are included in `PackNotice` immediately. Dye Slot 0 is reserved/protected for original colors and Slot 1 is unlocked by default (QOL). `scene_outfit` sends saved dye colors so placed plaza NPCs reflect actual dyes live.
  - **World Challenges, Scenic Spots, Riddles (`world.py`):** Scenic Spots (`EMissionType_ScenicSpot`) complete immediately without `battle_state='Finish'`; World Challenges & Riddles set `state='Finish'` and spawn official `boxId=2002`.
  - **Opened chests (`world.py`):** Archived/opened chests always emit `type='ETreasureBoxType_Normal'` + `TreasureBoxState_Open` so claimed chests stay visually open; red/big chests drop 2 gear + 20 Starstones.
  - **Atlas moonstones (`misc.py`):** `551xxxxx` moonstone lookup resolves via `StoneRewardQuestData -> StoneAreaData`.
  - **Starter profile & hygiene (`player.py`, `events.py`, `rozefield_server.py`):** New accounts start with Fei avatar (`41101`), default phone wallpaper (`8000`) & case (`7000`); Battle Pass & Turntable deduplicated to 1 active season; `ConnectionResetError` caught cleanly during HTTP download drain; GM `/set` and `/take` commands added with currency aliases.
- **Official World Level 0–5 Scaling (Build 53):**
  - Added `world_levels` (`0..5`) to `packs/official/systems/world.json` with official chest gold multipliers (`1.00x–2.25x`), Epic+ drop bonuses (`0%–80%`), and max gear levels.

---

## 3. Gameplay Features & QOL (Builds 54–59)

### Co-op Minimum Players & Fishing Rod Shop Rework (Builds 54–55, 59)
- **Co-op min players (`3 -> 2`):** Updated `packs/official/systems/coop.json`, `game/coop.py`, and client `teamgameplay.bytes` so small groups can launch Game Hall co-op modes (Pop Balloons, Aerial Adventure) with 2 players.
- **New player first recruit:** First recruit 100% guarantees Shiika (`102001`) to match the prologue story (`game/handlers.py`).
- **Chang's Lifestyle Store (`16000`) & Sherry (`15000`):** Moved all 10 Fishing Rods (`1006001–1006010`) into Chang's Store via `packs/official/systems/shops.json` and removed rods from Sherry, keeping official currencies and pricing the 3 unpriced rods (`1006004/1006007/1006008`) in Feline Tokens (`109`: `5,000 / 8,000 / 12,000`) to encourage co-op play.
- **Practical Fishing Rod (`1006004`) icon fix (Build 59):** Investigation showed `1006004` had its 3D prefab (`weapon_fishingrod_04.prefab`) and saved correctly in player inventory, but `icon_caijidaoju_yugan_04` was the **only** rod icon missing from the client YooAsset manifest (`0/3` PNGs vs `3/3` for the other 9 rods). Patched `Icon 1006004` in `ui.bytes` to reuse `icon_caijidaoju_yugan_01` so it renders and equips cleanly.

### Co-op: Snakes & Ladders in Rota Plaza (Build 56)
- **Direction:** Rather than hacking a 3rd compiled mode into the official Game Hall UI (which only handles `1001` Balloon and `1002` Platform in C#), we built Snakes & Ladders (`server/game/snakes_ladders.py`) directly in Rota Plaza using **in-game Special Dice (`item 2020`)**.
- **How it works:** `ThrowDiceReq` (`game/events.py`) already sends the exact rolled pip face (`req['pips']`, 1–6) from the client's 3D dice throw. Players use `/sl start`, `/sl join`, `/sl status`, `/sl board`, `/sl leave` in chat; Special Dice are auto-topped-up and not consumed during a match. Reaching Tile 30 awards **10,000 Feline Tokens** to the winner and **5,000** to each participant.

### Rota Plaza Park Invisible Wall & Resource Patch Pipeline (Build 56, 57, 59)
- **Unified patch builder (`devtools/build_rozefield_patch.py`):** Consolidates all Rozefield client resource edits into one repeatable script that updates the two patched bundles and regenerates the YooAsset 2.x manifest (`devtools/yoo.py`):
  1. `assets_scenes_home_scene.bundle`: Keeps `活动家具` (event furniture) off AND disables `包围盒v1` (the active plaza perimeter `MeshCollider` invisible wall) so players can walk freely behind the park area.
  2. `pbstaticconfigure.bundle`: Applies default stage (`scene.bytes`), Chang/Sherry shop overrides (`shop.bytes`), Co-op `PlayerMin = 2` (`teamgameplay.bytes`), Shovel-slot Umbrella Tools (`weapon.bytes` + `item.bytes`), and Practical Fishing Rod icon fallback (`ui.bytes`).

### Umbrella Tool in Temporary Shovel Slot (Build 57) & Toast Fix (Build 58)
- **Why Shovel slot (`NewWeaponType = 22`) instead of Bug Net (`7`):** Replacing Bug Net would make bug-catching use an umbrella. The unused Shovel slot (`22`) keeps Bug Net 100% intact until a dedicated IL2CPP tool slot is added.
- **How it works:** `build_rozefield_patch.py` injects 203 umbrella weapon models (`1070000 + umbrellaId`, `NewWeaponType = 22`, `NormalSpellID = 1004000` Bug Net over-the-shoulder idle pose) and 240 items into `weapon.bytes` / `item.bytes`. On login and on `UpdateCharacterAppearanceReq`, `player.sync_umbrella_tool()` automatically creates/equips the matching `shovelInstanceId` for whichever Umbrella is selected in **Fitting Room → Skin → Umbrella**.
- **9× Toast Spam Fix (Build 58):** Returning the entire 9-field `characterAppearance` dict in `UpdateCharacterAppearanceRsp` caused the client to fire 1 toast per field (9× `"Umbrella updated."` / `"Fishing Rod updated."`). Fixed by returning only the changed field(s) (`req.get('appearance', {})`) while persisting the full `characterAppearance` on the server.

### Official Exploration Fatigue (`探索疲労`, Build 58)
- **Direction:** Replaced hardcoded `playerDropRateInfo: {100, 100}` in `game/player.py` with the real `GlobalConfig` decay system:
  - `TreasureDrop_Decay_Ratio = 0.01` (`-1%` per field chest, floor `10%`), `BattleDrop_Decay_Ratio = 0.01` (`-1%` per field kill, floor `10%`), configurable in `packs/official/systems/world.json`.
  - Resets daily to `100% / 100%`, pushes live updates via official `PlayerTiredDropNotice` (`msg_id 2018`), scales field chest & monster kill drops in `game/world.py`, and stops bonus field materials at `<= 20%` kill conversion rate.

---

## 4. Client Binary Plugin Direction (Track A — BepInEx 6 IL2CPP)
- **Why needed:** Some mechanics are enforced strictly inside `GameAssembly.dll` (Unity `2021.3.45f2c1` IL2CPP x64), such as:
  1. Preventing `Friendship's Weight` (`4645001`, `NewFashionType = 6`, `IsCanSit = 1`) from being used together with a Vehicle (`VehicleSystem` / `IsInVehicle` / `ReqSceneSitVehicle`).
  2. Adding a true dedicated `NewWeaponType` slot for the Umbrella Tool without borrowing the Shovel slot.
- **Critical proxy rule (`winhttp.dll` → `doorstop.dll` chain):** The Rozefield client already uses `winhttp.dll` as its SDK/login proxy, and Windows maps `System32\version.dll` early via system DLLs (bypassing a local `version.dll`). Therefore, `server/link_relay/rozefield_link.c` now optionally chain-loads `doorstop.dll` right inside `DllMain` when present next to `winhttp.dll` (zero overhead when absent). Rename BepInEx's `winhttp.dll` to `doorstop.dll` so both Rozefield login and BepInEx 6 load cleanly together.
- **Workflow:** First launch generates `BepInEx/interop/` from `GameAssembly.dll`, after which small surgical Harmony hooks can be compiled with `.NET SDK` without corrupting base game binaries or mechanics.
