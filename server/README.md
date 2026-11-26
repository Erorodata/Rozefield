# Rozefield server — run OverField offline / on your own server

Status: **first playable-path build, not yet tested against the real client.**
The gate protocol, all 733 message IDs and all 2,308 message schemas were recovered from the client,
and the server replays a full captured login (session 4) correctly in a local test.

## How the client finds a server (recovered from GameAssembly.dll)
1. `StreamingAssets/Config.txt`: `UseCustomConfig = TRUE` + `RemoteServerIP` → custom dispatch address.
2. Otherwise HTTPDNS `http://8.134.240.36/resolve?domain=dsp-global-of.inutan.com…` → dispatch `:18881`.
3. Dispatch: `/dispatch/get_login_url_list`, `/dispatch/client_hot_update` (gives `hotOssUrl` CDN and resource version),
   `/dispatch/region_info` (gives gate IP/port), `/dispatch/get_notice_list`, `/dispatch/get_notice_url_list`.
4. Login SDK: game listens on named pipe `\quickpc<game process id>` and launches `PCSDKUI.exe`; the SDK writes one JSON
   message per connection (`{"action":"init"}`, then `{"action":"loginSuccess","params":{uid,authToken,userToken,username,timeleft}}`).
   `sdk_stub/PCSDKUI.exe` replaces the web login and sends those two messages straight away.
5. Gate TCP `:11001`: frame = `u16 big-endian header length` + `pb.PacketHead` + body.
   `PacketHead{packet_id=1, msg_id=2, flag=3, body_len=4, total_pack_count=5, seq_id=6}`; `flag=1` means the body is
   raw Snappy. Response id = request id + 1 and echoes `packet_id`; pushes carry an increasing `seq_id`.
   Message ids are the custom option `10001` on each message in `player.proto` (see `proto/msgids.json`).

## Files
| Path | What |
|---|---|
| `rozefield_server.py` | dispatch HTTP (+HTTPDNS, +hot-update file host) and gate server |
| `ofproto.py` | schema loader, framing, Snappy |
| `proto/overfield.desc` | FileDescriptorSet: 154 files (net: `enum`, `common`, `player`; plus 151 config-table schemas) |
| `proto/net/*.proto`, `proto/config/*.proto` | readable .proto text (msg ids in comments) |
| `tools/make_save.py` | build `save/save.json` from your own pcaps (your account — keep private) |
| `tools/re/` | the extraction scripts (literal xrefs → descriptor reassembly → ids) |
| `sdk_stub/` | offline PCSDKUI.exe replacement (source + build) and `rozefield_sdk.ini` |
| `setup_client.ps1` | switch the game to this server / `-Revert` |
| `start_server.bat` | run the server on Windows |

## Use (Windows)
1. Install Python 3 (python.org, tick "Add to PATH").
2. Build a save from your captures: `py tools\make_save.py <capture.pcapng>... -o save\save.json`
   and put your SDK uid in `rozefield_sdk.ini`.
3. Admin PowerShell: `powershell -ExecutionPolicy Bypass -File setup_client.ps1`
4. Run `start_server.bat`, then start the game. Watch `server.log`; every message is also logged to `traffic.jsonl`.

## What works / what doesn't yet
* Login, main data, login pushes, every request seen in the captures (replayed), pings, scene channel change.
* Unseen requests get an empty `StatusCode_OK` reply of the right type.
* State does not persist yet (placing furniture, cooking, gacha etc. return the captured answer, not a new result).
  Making those real is the next step: implement handlers per request in `Session`, using the config tables
  (`proto/config`, data in the YooAsset bundles) — gacha rates are in README §2d.
* Co-op/other players: single player only.

Build the stub: `python -m ziglang cc -target x86_64-windows-gnu -O2 -Wl,--subsystem,windows -s -o PCSDKUI.exe pcsdkui_stub.c`

## Rozefield features (differences from official, on purpose)

| Feature | What it does | How |
|---|---|---|
| Default plaza look | The plaza never shows event decorations: no seasonal stage (event lawn, Ferris wheel, Halloween stage) and no event furniture (the scene's "活动家具" group: Halloween trees, ghosts, pumpkins, cake world, voxel buildings) | Patch: event `SceneTheme` rows have no dates (`tools/default_stage.py`); the home scene bundle has the event furniture group switched off (`tools/plaza_event_furniture.py`) |
| Spawn rules | Login: plaza spawn. Entering the plaza from anywhere else: plaza spawn. Switching plaza channel / visiting another plaza from the plaza: you keep your position. Maps and fields: their start point (a teleport point you pick is used). Sequences: the Sequence's own start point. Leaving a Sequence: back at its entrance | `game/handlers.py` (`change_scene`), `game/dungeon.py`, `game/dungeon_starts.json` |

## Hosting (one device is the server, every PC just plays)

| Who | What to do |
|---|---|
| Host, Windows | Put the `Server` folder next to the `Overfield` folder. No Python installed? Run `setup_python.bat` once. Start `Rozefield Server.exe`. Hosting > Start with Windows keeps it in the tray from boot (log-in) on |
| Host, Linux / mini PC / VPS | Copy the `Server` folder (and `Overfield` beside it if you have it), then `sudo ./install_linux.sh`: a service that starts on boot. Set the panel password with `./start_server.sh --set-admin-password <password>`. Open TCP 80, 18881, 11001 |
| Host, control from your PC | `Rozefield Server.exe` > Connect: the device's address and its admin password. Every request is signed; the password is never sent |
| Host, fixed name | Hosting > Name service `duckdns` (free name + token from duckdns.org) or `url` (own domain's dynamic-DNS update URL, `{ip}` = address). The server keeps it pointed at itself |
| Host, router | Hosting > Open router ports (UPnP). If the router refuses, forward TCP 80, 18881, 11001 to the server by hand |
| Host, give players the game | Game package builds `downloads\Rozefield.zip` (the Overfield folder with this server as default). Players get it from `http://<server name>/` or the Drive link set in Hosting |
| Host, move to a new device | Move server > Yes (export one file) on the old one; on the new one Move server > No (import), restart. Players change nothing if the fixed name moved with it |
| Host, imports | Imports lists every official backup / Rozefield account brought in; Undo puts the account back (or removes it if it was new) |
| Player | Unzip and start `launcher.exe`. The login window has the server at the top: the default one is already chosen; + takes an invite code (`RZ-XXXX-XXX`, shown in Hosting), a name or an address; the search button lists home-network servers. Picking another server and pressing Enter game restarts the game on that server, logged in. Create account, or Bring my account (official backup `.rzsave` / Rozefield account `.rzaccount`). No admin rights |
| Player, change server | Export account (`.rzaccount`) in the login window, pick the other server, type the name you want there, Bring my account |

A server list kept on GitHub (or any https page) works too: put `"list_url": "https://.../servers.json"` in the game's
`rozefield_servers.json`; Hosting's `servers.json` (`/admin/host/servers.json`) gives the content.

## Play with friends the old way (setup_client.ps1, still works)

The server answers every player with the address they reached it on, so players on the host PC, the LAN and the
internet can play together at the same time. Co-op (Pop Balloons, Aerial Adventure: all 10 layouts each, team
invites), online Gomoku, chat, plazas, friends and the wish list work across PCs.

| Step | Who | What |
|---|---|---|
| 1 | Host | `start_server.bat` as usual |
| 2 | Host | `allow_friends.bat` (as Administrator) once: opens TCP 80, 18881, 11001 and shows your LAN and internet address |
| 3 | Host | For internet play: forward TCP 80, 18881 and 11001 on the router to this PC |
| 4 | Host | `make_friend_kit.bat`, then send `Rozefield_friend_kit.zip` and a copy of the game folder (without `_archive`) |
| 5 | Friend | Unzip the kit; in an Administrator terminal: `powershell -ExecutionPolicy Bypass -File setup_client.ps1 -Game "<game folder>" -ServerIP <host address>` |
| 6 | Friend | Start `launcher.exe`; the first start downloads the Rozefield update from the host; create an account and play |

`setup_client.ps1` points the login window, `Config.txt` and the game's own server lookup at the host (no Python
needed). The lookup address must fit in 12 characters; for a longer one add `-LookupName rozefield` (it also adds
`<host address> rozefield` to the hosts file). Undo with `-Revert`.

## Saving player accounts before the official shutdown (backup / import)

**Easiest:** give players `backup_tool\Rozefield Backup.exe` (single file, nothing to install). They press
**1. Open OverField (Official)**, log in as usual, open the menus in the checklist, and close the game: the backup
(`backups\<name>_<date>.rzsave`) is saved automatically (or press **2. Save backup**). Later, in the Rozefield login
window, **Import backup (.rzsave)...** uploads it and the account appears under their in-game name. Re-importing the
same account replaces it (the previous save is kept as `<id>.json.before_import_<time>`); a name already used by a
different account is refused.

The backup never keeps the login token or device details (account SDK id, device id and model, analytics id,
log-server token, the game's client logs); the server also drops them from older backups when importing.

Script version of the same:

**Players (while the official server is still online):** run `export_my_data.bat`, then start OverField normally and log
in. The tool relays your game's connection to the official server unchanged and records what the server sends about
your account (it sends nothing of its own and does not save your login token). Open the menus it lists (achievements,
life skills, manual, plaza...) so those are saved too, close the game, press Ctrl+C. You get
`exports\<name>_<date>.rzsave`. Config.txt is put back as soon as the game has connected; if the window was closed
early, running the .bat again restores everything.

**Server host:** drag `.rzsave` files onto `import_player.bat` (or `py tools\import_player.py file.rzsave [--name X]`).
The player then types their in-game name in the Rozefield login box and continues where they left off. Any other name
starts a fresh account.
