"""One port for everything (default 18880), so a server needs only one router port or one playit.gg tunnel.

A connection that starts with  RZL1 gate\\n  goes to the game port; anything else (HTTP from the game, the login
window, the panel or a browser) goes to the HTTP port, bytes untouched. The Rozefield file in the player's game
folder (winhttp.dll) sends everything here; the server answers it with 127.0.0.1 addresses, which that file serves.
"""
import asyncio
import logging

log = logging.getLogger('rozefield')
MAGIC = b'RZL1 '
LINK_PORT = 18880


async def _pipe(r, w):
    try:
        while True:
            b = await r.read(65536)
            if not b:
                break
            w.write(b)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


def handler(http_port, gate_port):
    async def handle(reader, writer):
        try:
            first = await asyncio.wait_for(reader.read(len(MAGIC)), 15)
            if not first:
                writer.close(); return
            target, rest = http_port, first
            if first == MAGIC:
                line = await asyncio.wait_for(reader.readline(), 15)
                kind = line.strip().decode('latin1', 'replace')
                if kind == 'gate':
                    target, rest = gate_port, b''
                elif kind == 'http':
                    target, rest = http_port, b''
                else:
                    writer.close(); return
            # from 127.0.0.2, so the server never mistakes a link connection for this PC (the panel's local login)
            try:
                ur, uw = await asyncio.open_connection('127.0.0.1', target, local_addr=('127.0.0.2', 0))
            except OSError:
                ur, uw = await asyncio.open_connection('127.0.0.1', target)
        except Exception:
            try:
                writer.close()
            except Exception:
                pass
            return
        if rest:
            uw.write(rest)
        await asyncio.gather(_pipe(reader, uw), _pipe(ur, writer))
    return handle


async def start(bind, link_port, http_port, gate_port):
    try:
        srv = await asyncio.start_server(handler(http_port, gate_port), bind, link_port)
    except OSError as e:
        log.warning('link port %s not available (%s): players from outside use the separate ports', link_port, e)
        return None
    log.info('link port %s: one port for players from anywhere (router or playit.gg tunnel to this port)', link_port)
    return srv
