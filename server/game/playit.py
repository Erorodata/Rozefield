"""Built-in playit.gg: an internet address for this server that works through any router or provider (CGNAT).

On Windows, when the router didn't open the link port by itself, the server
  1. downloads playit's own background program (playitd, from playit's GitHub releases) into Server/playit/,
  2. the first time only: asks the host to sign in once (the panel opens https://playit.gg/claim/<code>),
     then keeps the agent key in save/playit.toml,
  3. runs playitd with that key and makes sure there is one TCP tunnel to the link port,
  4. saves the tunnel's address (word-word.gl.at.ply.gg:12345) as the server's internet address.
The address never changes after that, so game packages carry it and players just install and play.

Talks to https://api.playit.gg (the same calls playit's own programs make: claim/setup, claim/exchange,
v1/agents/rundata, v1/tunnels/create), authorised with the agent key.
"""
import json
import logging
import os
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger('rozefield')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://api.playit.gg'
DIR = os.path.join(HERE, 'playit')
EXE = os.path.join(DIR, 'playitd.exe')
URL = 'https://github.com/playit-cloud/playit-agent/releases/latest/download/playitd-windows-x86_64.exe'
SECRET = os.path.join(HERE, 'save', 'playit.toml')
STATE = {'state': 'off', 'url': '', 'address': '', 'msg': ''}
_proc = None
_lock = threading.Lock()
_wake = threading.Event()


def _set(**kw):
    STATE.update(kw)


def _api(path, body, key=None, timeout=20):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'OverfieldServer'})
    if key:
        req.add_header('Authorization', f'Agent-Key {key}')

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:   # playit answers "fail" with HTTP 400 and the reason in the body
        try:
            res = json.loads(e.read().decode('utf-8'))
        except Exception:
            raise RuntimeError(f'{path}: HTTP {e.code}')
    st = res.get('status')
    if st == 'success':
        return res.get('data')
    raise RuntimeError(f"{path}: {st} {json.dumps(res.get('data'))[:200]}")


def _read_key():
    try:
        for line in open(SECRET, encoding='utf-8'):
            if line.strip().startswith('secret_key'):
                return line.split('=', 1)[1].strip().strip('"').strip()
    except OSError:
        pass
    return ''


def _download():
    if os.path.exists(EXE):
        return True
    os.makedirs(DIR, exist_ok=True)
    _set(state='starting', msg='downloading playit (once)')
    log.info('playit.gg: downloading playit (once, from playit\'s GitHub releases)...')
    tmp = EXE + '.tmp'
    try:
        req = urllib.request.Request(URL, headers={'User-Agent': 'OverfieldServer'})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
        os.replace(tmp, EXE)
        return True
    except Exception as e:
        _set(state='error', msg=f'could not download playit: {e}')
        log.warning('playit.gg: could not download playit (%s)', e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _claim():
    """Sign in once: a claim code the host approves on playit.gg, exchanged for the agent key."""
    code = secrets.token_hex(5)
    url = f'https://playit.gg/claim/{code}'
    shown = False
    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        try:
            st = _api('/claim/setup', {'code': code, 'agent_type': 'self-managed', 'version': 'Overfield Server 1.1'})
        except Exception as e:
            _set(state='error', msg=str(e)); log.warning('playit.gg: %s', e); return ''
        if not shown:
            _set(state='claim', url=url, msg='sign in once on playit.gg')
            log.info('playit.gg sign-in (once): %s', url)
            shown = True
        if st == 'UserAccepted':
            break
        if st == 'UserRejected':
            _set(state='off', url='', msg='playit sign-in was declined'); return ''
        _wake.wait(3); _wake.clear()
    else:
        _set(state='off', url='', msg='playit sign-in not finished'); return ''
    for _ in range(40):
        try:
            key = _api('/claim/exchange', {'code': code})['secret_key']
            os.makedirs(os.path.dirname(SECRET), exist_ok=True)
            with open(SECRET, 'w', encoding='utf-8') as f:
                f.write(f'secret_key = "{key}"\n')
            _set(url='')
            log.info('playit.gg: signed in')
            return key
        except Exception:
            time.sleep(3)
    _set(state='error', msg='playit sign-in could not be completed'); return ''


def _run(key):
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            return
        flags = 0x08000000 if os.name == 'nt' else 0   # no console window
        _proc = subprocess.Popen([EXE, '--secret-path', SECRET, '--log-path', os.path.join(DIR, 'playitd.log')],
                                 cwd=DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=flags)


def _tunnel(key, link_port):
    """The TCP tunnel to the link port: find it, or make it; returns its public address."""
    for attempt in range(60):
        try:
            rd = _api('/v1/agents/rundata', {}, key)
        except Exception as e:
            _set(msg=f'waiting for playit ({e})'); time.sleep(5); continue
        for t in rd.get('tunnels', []):
            fields = {f['name']: f['value'] for f in (t.get('agent_config') or {}).get('fields', [])}
            if fields.get('local_port') == str(link_port) and t.get('display_address'):
                return t['display_address']
        if any(str(link_port) in json.dumps(p) or 'Overfield' in p.get('name', '') for p in rd.get('pending', [])):
            time.sleep(5); continue
        if attempt == 0 or attempt % 12 == 0:
            try:
                _api('/v1/tunnels/create', {
                    'ports': {'type': 'custom-tcp', 'details': 1},
                    'origin': {'type': 'agent', 'data': {'agent_id': None, 'config': {'fields': [
                        {'name': 'local_ip', 'value': '127.0.0.1'}, {'name': 'local_port', 'value': str(link_port)}]}}},
                    'enabled': True, 'alloc': None, 'name': 'Overfield', 'firewall_id': None}, key)
                log.info('playit.gg: tunnel to port %s requested', link_port)
            except Exception as e:
                log.warning('playit.gg: could not make the tunnel (%s); add a TCP tunnel to local port %s on playit.gg',
                            e, link_port)
                _set(msg=f'add a TCP tunnel to local port {link_port} on playit.gg')
        time.sleep(5)
    return ''


def _main(link_port, router_open):
    from game import hostcfg
    s = hostcfg.load()
    if s.get('tunnel', 'auto') == 'off':
        _set(state='off', msg='turned off in Hosting'); return
    key = _read_key()
    if not key and router_open() and not s.get('playit_wanted'):
        _set(state='off', msg='not needed: the router opened the port'); return
    if not _download():
        return
    if not key:
        key = _claim()
        if not key:
            return
    _set(state='starting', msg='connecting to playit')
    _run(key)
    addr = _tunnel(key, link_port)
    if not addr:
        _set(state='error', msg=STATE.get('msg') or 'no tunnel address yet'); return
    _set(state='online', address=addr, msg='')
    if hostcfg.load().get('tunnel_address') != addr:
        hostcfg.update({'tunnel_address': addr})
    log.info('playit.gg: players anywhere use %s', addr)
    while True:   # keep playit running with the server
        time.sleep(30)
        with _lock:
            dead = _proc is None or _proc.poll() is not None
        if dead:
            log.info('playit.gg: playit stopped, starting it again'); _run(key)


_args = {}
_running = threading.Event()


def start(link_port, router_open, delay=8):
    """router_open(): True when the router opened the link port (then playit isn't needed)."""
    if os.name != 'nt' or not link_port or _running.is_set():
        return
    _args.update(link_port=link_port, router_open=router_open)
    _running.set()
    def go():
        time.sleep(delay)   # give the router (UPnP) a moment first
        try:
            _main(link_port, router_open)
        except Exception as e:
            _set(state='error', msg=str(e)); log.exception('playit.gg')
        finally:
            if STATE.get('state') != 'online':
                _running.clear()
    threading.Thread(target=go, daemon=True).start()


def want_now():
    """Share > Use playit.gg: use it even though the router is open, and show the sign-in again if needed."""
    from game import hostcfg
    hostcfg.update({'playit_wanted': True, 'tunnel': 'auto'})
    _wake.set()
    if _args and not _running.is_set():
        start(_args['link_port'], _args['router_open'], delay=0)
    return STATE


def stop():
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
