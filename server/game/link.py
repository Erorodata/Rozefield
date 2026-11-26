"""One port for everything (default 18880), so a server needs only one router port or one playit.gg tunnel.

A connection that starts with  RZL1 gate\\n  is a game connection; anything else (HTTP from the game, the login
window, the panel or a browser) is HTTP. Both are served right here by the server's own handlers. The Rozefield file in the player's game
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


def handler(http_handle, gate_handle):
    """Serve the link port directly with the server's own HTTP and game handlers (no hop through 18881 / 11001,
    so the link works even when another program on this PC holds those ports)."""
    async def handle(reader, writer):
        try:
            first = await asyncio.wait_for(reader.readexactly(len(MAGIC)), 15)
        except Exception:
            writer.close(); return
        kind, rest = 'http', first
        if first == MAGIC:
            try:
                kind = (await asyncio.wait_for(reader.readline(), 15)).strip().decode('latin1', 'replace')
            except Exception:
                writer.close(); return
            rest = b''
            if kind not in ('http', 'gate'):
                writer.close(); return
        r2 = reader
        if rest:   # put the sniffed bytes back in front of the stream
            r2 = asyncio.StreamReader(limit=2 ** 20)
            r2.feed_data(rest)
            async def feed():
                try:
                    while True:
                        b = await reader.read(65536)
                        if not b:
                            break
                        r2.feed_data(b)
                finally:
                    r2.feed_eof()
            asyncio.ensure_future(feed())
        if first == MAGIC:
            writer.rz_link = True   # from the Rozefield link: answers carry 127.0.0.1, which it serves on the player's PC
        h = gate_handle if kind == 'gate' else http_handle
        if h is None:
            writer.close(); return
        await h(r2, writer)
    return handle


async def start(bind, link_port, http_handle, gate_handle):
    try:
        srv = await asyncio.start_server(handler(http_handle, gate_handle), bind, link_port)
    except OSError as e:
        log.warning('link port %s not available (%s): players from outside use the separate ports', link_port, e)
        return None
    log.info('link port %s: one port for players from anywhere (router or playit.gg tunnel to this port)', link_port)
    return srv
