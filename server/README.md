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

## Saving player accounts before the official shutdown (backup / import)

**Easiest:** give players `backup_tool\OverField Backup Data.exe` (single file, nothing to install). They press
**1. Open OverField (Official)**, log in as usual, open the menus in the checklist, and close the game: the backup
(`backups\<name>_<date>.rzsave`) is saved automatically (or press **2. Save backup**). Later, in the Rozefield login
window, **Import backup (.rzsave)...** uploads it and the account appears under their in-game name. Re-importing the
same account replaces it (the previous save is kept as `<id>.json.before_import_<time>`); a name already used by a
different account is refused.

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
