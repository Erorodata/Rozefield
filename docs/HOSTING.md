# Host your own Rozefield server

| Who | What to do |
|---|---|
| Host | Open **Overfield Server** and press **Start**. That's all. |
| Players on your Wi-Fi | Start `launcher.exe`, then **Find on my network** in the login window. |
| Players anywhere | Start `launcher.exe` and type the server's internet address (Share shows it). Players who download the game from your server's page are already set to it. |

## Players from anywhere (playit.gg, built in)

When your router doesn't open port **TCP 18880** by itself, Start sets up playit.gg for you:

1. The first time only, a playit.gg page opens. Sign in there (free).
2. Overfield Server makes the tunnel and shows the address in the log, e.g. `word-word.gl.at.ply.gg:12345`.
3. The address never changes. **Share** shows it, and **Game package** puts it in the game download.

This works with any router or internet provider, including ones that share one internet address between customers (CGNAT).
Turn it off in **Hosting** if you only play on your own network.

## Windows Firewall

The first Start asks Windows once (press **Yes**) to let players in on TCP 18880.

## Another PC as the server

Copy the Server folder to that PC and press **Start** there. Control it from your own PC with **Connect…**
(set an admin password in Hosting on the server PC first).
