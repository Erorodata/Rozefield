# Host your own Rozefield server with a DuckDNS name

A free DuckDNS name (e.g. `myserver.duckdns.org`) gives your server an address that never changes. Players add it once.
Overfield Server keeps the name pointed at your internet address by itself, even when your provider changes it.

Time needed: about 15 minutes. Cost: free.

> **Simpler: playit.gg.** If you'd rather not touch your router, or your internet provider blocks incoming
> connections (CGNAT, common on mobile and some fibre plans), use **Share > Use playit.gg** instead. It gives your
> server an address that works from anywhere, and you don't need DuckDNS at all. Players install nothing.
>
> Using DuckDNS? Your server now needs only **one port forwarded: TCP 18880**.

The quickest way: **Setup** in the panel's sidebar walks you through steps 1 to 5 (it also opens by itself the first
time). This page explains the same steps in detail.

## What you need

| Item | Notes |
|---|---|
| The `Server` folder and the `Overfield` folder side by side | e.g. `H:\Backup\Server` and `H:\Backup\Overfield` |
| A PC (or mini PC / VPS) that stays on while people play | Linux works too: see `server/README.md` |
| Access to your home router's settings page | Usually `192.168.0.1` or `192.168.1.1`; the login is often on a sticker on the router |
| A Google, GitHub, Reddit or X (Twitter) account | To sign in at duckdns.org |

## Step 1: Get a DuckDNS name and token

1. Go to https://www.duckdns.org and sign in with one of the listed accounts.
2. In **domains**, type the name you want (letters, numbers, `-`), e.g. `myserver`, and press **add domain**.
   Your server name is now `myserver.duckdns.org`.
3. At the top of the page, copy your **token** (a long code like `a7c4d0ad-114e-40ef-...`).
   Treat it like a password: anyone with it can move your name. If it leaks, make a new one on duckdns.org and put
   the new one in Rozefield.

## Step 2: Put them into Overfield Server

1. Start `Overfield Server.exe` and press **Start**.
2. Press **Hosting** and fill in:

| Field | What to type |
|---|---|
| Display name | What players see in their server list, e.g. `Rozefield - Wazein` |
| Fixed server name | The full name: `myserver.duckdns.org` |
| Name service | `duckdns` |
| DuckDNS token | The token from step 1 |
| Open router ports automatically | `yes` |
| Start with Windows | `yes`, if this PC should host whenever it is on |

3. Press **OK**. The message at the end should say `Server name: myserver.duckdns.org -> <your internet address>`.
   If it says DuckDNS refused the update, check the name and the token.

From now on the server re-checks every 10 minutes and moves the name if your internet address changes.

## Step 3: Open the ports in your router

Players on the internet must be let through your router to this PC.

1. Press **Share** in the panel. If there's no yellow note, the router opened the ports by itself (UPnP): go to
   step 4.
2. Otherwise, note **this PC's home address** from the yellow note (e.g. `192.168.1.20`) and open your router's page.
3. Find **Port Forwarding** (sometimes **Virtual Server**, **NAT** or **Applications**) and add three rules:

| Name | Protocol | External port | Internal port | Device / internal IP |
|---|---|---|---|---|
| Rozefield lookup | TCP | 80 | 80 | this PC's home address |
| Rozefield dispatch | TCP | 18881 | 18881 | this PC's home address |
| Rozefield game | TCP | 11001 | 11001 | this PC's home address |

4. In the same router, give this PC a fixed home address (**DHCP reservation** / **static lease**), so the rules
   keep pointing at it after a restart.
5. On this PC, run `allow_friends.bat` as administrator once (opens the same ports in Windows Firewall).
6. Back in **Share**, press **Check router again**.

## Step 4: Check it from outside

Testing from your own Wi-Fi can fail even when everything works (many routers don't loop back). Use a phone on mobile
data instead:

| Test | Expected |
|---|---|
| Open `http://myserver.duckdns.org/` on the phone (Wi-Fi off) | The Rozefield download page |
| Ask a friend to add `myserver.duckdns.org` with **+** in the login window | Status shows **Online** |

## Step 5: Give players the game and the name

1. **Game package** in the panel builds `Rozefield.zip` with your server already set as the default.
   Optional: upload it to Google Drive and put the share link in Hosting > Download link (faster for players).
2. **Share > Copy invite message** and paste it in your chat. It has the download link, your server name and the
   steps.
3. Players who already have OverField can use **Overfield Backup > Play on Rozefield** with `myserver.duckdns.org`
   instead of downloading the game.

## If it doesn't work

| Problem | Likely cause | What to do |
|---|---|---|
| Hosting says DuckDNS refused the update | Wrong name or token | Copy both again from duckdns.org |
| The download page doesn't open from mobile data, ports look right | Your provider shares one internet address among many homes (carrier-grade NAT): the address in your router's status page differs from the one in Share | Ask your provider for a public IP address, or host on a VPS |
| The page opens but the game can't connect | Port 18881 or 11001 not forwarded, or the firewall blocked it | Check the three rules and run `allow_friends.bat` again |
| Only port 80 fails | Some providers block port 80 for homes | Players can still join; put the game on Google Drive and set the Download link |
| It worked yesterday, not today | This PC got a new home address | Set the DHCP reservation (step 3.4) and fix the rules |
| Works on your Wi-Fi only | Router doesn't loop back | Test with mobile data (step 4); friends outside are fine |

## Moving to another device later

Move server > export on the old device, import on the new one, then fill in Hosting there with the same DuckDNS name
and token. The name follows the new device within minutes; players change nothing.
