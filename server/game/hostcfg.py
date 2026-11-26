"""Host settings (save/server_settings.json) and the admin password used by the control panel from another device.

Remote panel requests are signed, never sent with the password itself:
    X-Admin-Time: <unix seconds>
    X-Admin-Sig:  hex HMAC-SHA256(key, "<time>\\n<METHOD>\\n<path with query>\\n" + hex SHA-256(body))
key = PBKDF2-HMAC-SHA256(password, salt, ROUNDS, 32 bytes). The salt and round count are public (GET /admin/salt).
A signature is accepted once, within 5 minutes of its time.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(HERE, 'save', 'server_settings.json')
ROUNDS = 100000
DEFAULTS = {
    'display_name': 'Rozefield',      # shown in the launcher's server list and on the download page
    'name_provider': 'none',          # none | duckdns | url
    'server_name': '',                # the fixed name players use, e.g. myserver.duckdns.org
    'duckdns_token': '',
    'update_url': '',                 # own domain: a dynamic-DNS update URL, {ip} is replaced by the public address
    'upnp': True,                     # open the router ports automatically
    'download_link': '',              # e.g. a Google Drive link to Rozefield.zip (tried before this server)
    'public_list': False,             # offer servers.json for a server list on GitHub
    'lan_discovery': True,            # answer launchers looking for servers on the home network
    'tunnel': 'auto',                 # auto (router first, then playit.gg) | playit | off
    'tunnel_address': '',             # the playit.gg address players use, e.g. word-word.gl.at.ply.gg:12345
}
_lock = threading.Lock()
_seen = {}


def load():
    try:
        s = json.load(open(FILE, encoding='utf-8'))
    except Exception:
        s = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in s.items()})
    return out


def save(s):
    with _lock:
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        tmp = FILE + '.tmp'
        json.dump(s, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)


def public_view(s=None):
    """Settings as the panel shows them: secrets replaced by whether they are set."""
    s = dict(s or load())
    adm = s.pop('admin', None)
    s['admin_password_set'] = bool(adm)
    if s.get('duckdns_token'):
        s['duckdns_token'] = '(set)'
    return s


def update(changes):
    s = load()
    for k, v in changes.items():
        if k not in DEFAULTS:
            continue
        if k == 'duckdns_token' and v == '(set)':
            continue
        if isinstance(DEFAULTS[k], bool):
            v = str(v).lower() in ('1', 'true', 'yes', 'on')
        s[k] = v
    save(s)
    return s


# ---------------------------------------------------------------- admin password
def derive(password, salt_hex, rounds=ROUNDS):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), rounds, 32)


def set_admin_password(password):
    if len(password) < 6:
        raise ValueError('use at least 6 characters')
    s = load()
    salt = secrets.token_hex(16)
    s['admin'] = {'salt': salt, 'rounds': ROUNDS, 'key': derive(password, salt).hex()}
    save(s)


def salt_info():
    adm = load().get('admin')
    return f"{adm['salt']}|{adm['rounds']}" if adm else ''


def check_signed(method, path, body, hdr):
    adm = load().get('admin')
    if not adm:
        return False
    try:
        t = int(hdr.get('x-admin-time', '0'))
        sig = bytes.fromhex(hdr.get('x-admin-sig', ''))
    except ValueError:
        return False
    now = time.time()
    if abs(now - t) > 300:
        return False
    msg = f'{t}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}'.encode()
    good = hmac.new(bytes.fromhex(adm['key']), msg, hashlib.sha256).digest()
    if not hmac.compare_digest(good, sig):
        return False
    with _lock:
        for k in [k for k, v in _seen.items() if v < now - 600]:
            del _seen[k]
        if sig in _seen:
            return False
        _seen[sig] = now
    return True


def sign(password_key_hex, method, path, body, t=None):
    """What the panel sends (used by tests and tools)."""
    t = int(t or time.time())
    msg = f'{t}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}'.encode()
    return t, hmac.new(bytes.fromhex(password_key_hex), msg, hashlib.sha256).hexdigest()
