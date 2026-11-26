"""Owner control panel API (used by Overfield Server.exe). Only answers requests from this PC (127.0.0.1) that carry
the token from save/admin_token.txt, so other players on the network can't use it.

    GET  /admin/players            one line per account: pid|uid|name|level|online|banned|muted|password|official|label
    GET  /admin/log?since=N        "next\\n" then the log lines after N
    POST /admin/do                 body: action, then key=value lines (values: \\n escaped as \\\\n)  ->  OK|text  or  ERR|text
"""
import collections
import json
import logging
import os
import secrets
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACC = os.path.join(HERE, 'save', 'accounts')
TOKEN_FILE = os.path.join(HERE, 'save', 'admin_token.txt')
OK = 'StatusCode_OK'


class Ring(logging.Handler):
    """The last lines of the server log, numbered, for the panel's live view."""
    def __init__(self, n=4000):
        super().__init__()
        self.lines, self.next = collections.deque(maxlen=n), 0

    def emit(self, record):
        try:
            self.lines.append((self.next, self.format(record))); self.next += 1
        except Exception:
            pass

    def since(self, n):
        return self.next, [t for i, t in self.lines if i >= n]


RING = Ring()
CHAT = collections.deque(maxlen=5000)   # (time, pid, name, channel, text): the chat log for moderation


def token():
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    t = secrets.token_hex(16)
    open(TOKEN_FILE, 'w').write(t)
    return t


def _accounts(server):
    from game.player import _registry
    reg = _registry()
    from rozefield_server import has_password
    out = []
    for uid, pid in reg['by_uid'].items():
        f = os.path.join(ACC, f'{pid}.json')
        if not os.path.exists(f):
            continue
        sess = server.sessions.get(pid)
        st = sess.p.s if sess and sess.p else json.load(open(f, encoding='utf-8'))
        out.append((pid, uid, st))
    return out


def players(server):
    from rozefield_server import has_password
    lines = []
    for pid, uid, st in sorted(_accounts(server), key=lambda x: (x[0] not in server.sessions, x[2].get('name', '').lower())):
        name = (st.get('name') or '').replace('|', '/')
        lines.append('|'.join(str(x) for x in (pid, uid, name, st.get('level', 1), int(pid in server.sessions),
                                               int(bool(st.get('banned'))), int(bool(st.get('muted'))), int(has_password(uid)),
                                               st.get('official_player_id') or 0, st.get('player_label', pid))))
    return '\n'.join(lines)


def _edit(server, pid, fn):
    from game.friends import edit
    return edit(server, pid, fn)


def _uid_of(pid):
    from game.player import _registry
    return next((u for u, p in _registry()['by_uid'].items() if p == pid), None)


def do(server, body):
    lines = body.decode('utf-8').split('\n')
    act, kv = lines[0].strip(), {}
    for l in lines[1:]:
        if '=' in l:
            k, v = l.split('=', 1); kv[k] = v.replace('\\n', '\n')
    try:
        return _do(server, act, kv)
    except Exception as e:
        logging.getLogger('rozefield').exception('admin %s failed', act)
        return f'ERR|{e}'


def _do(server, act, kv):
    from rozefield_server import set_password, _pw_load, PW_FILE
    log = logging.getLogger('rozefield')
    pid = int(kv.get('pid', 0) or 0)
    uid = _uid_of(pid) if pid else None
    sess = server.sessions.get(pid)

    if act in ('resetpw', 'clearpw', 'ban') and uid and server.login_keys.pop(uid, None):
        server.save_login_keys()      # the game's saved login stops working; they log in again with the new password
    if act == 'resetpw':
        if not uid or len(kv.get('password', '')) < 4:
            return 'ERR|Passwords need at least 4 characters.'
        set_password(uid, kv['password']); log.info('[admin] password reset for %s', uid)
        return 'OK|Password reset. Tell the player their new password.'
    if act == 'clearpw':
        d = _pw_load(); d.pop(uid, None); json.dump(d, open(PW_FILE, 'w', encoding='utf-8'))
        log.info('[admin] password cleared for %s', uid)
        return 'OK|Password removed. The next password used to log in becomes the new one.'
    if act == 'rename':
        name = kv.get('name', '').strip()
        if not name or len(name) > 24:
            return 'ERR|Names are 1-24 characters.'
        _edit(server, pid, lambda st: st.__setitem__('name', name)); log.info('[admin] %s renamed to %s', pid, name)
        return 'OK|Renamed (the player sees it after logging in again).'
    if act == 'gm':
        if not sess:
            return 'ERR|The player must be online for GM commands.'
        from game.handlers import gm_command
        sess.cur = None
        out = gm_command(sess, kv.get('cmd', '').strip())
        log.info('[admin] GM %s on %s: %s', kv.get('cmd'), pid, out)
        return 'OK|' + out
    if act == 'mail':
        items = []
        for part in (kv.get('items') or '').replace(' ', '').split(','):
            if ':' in part:
                i, n = part.split(':', 1); items.append({'itemId': int(i), 'num': str(int(n))})
        targets = [p for p, _, _ in _accounts(server)] if kv.get('to') == 'all' else [pid]

        def add(st):
            mails = st.setdefault('mails', [])
            m = {'mail_id': max([x.get('mail_id', 0) for x in mails] + [1232]) + 1, 'mail_state': 'MailState_UNREAD' if not items else 'MailState_UNCLAIM',
                 'sender': kv.get('sender') or 'Rozefield', 'content_type': 'MailContentType_TEXT', 'title': kv.get('title', 'Message'),
                 'content': kv.get('content', ''), 'overdueDay': 30, 'send_time': str(int(time.time())), 'items': items}
            mails.insert(0, m)
            return m
        for t in targets:
            box = {}
            _edit(server, t, lambda st: box.__setitem__('m', add(st)))
            s = server.sessions.get(t)
            if s and box.get('m'):
                try:
                    s.push('ReceiveMailNotice', {'status': OK, 'mail': box['m']})
                except Exception:
                    pass
        log.info('[admin] mail "%s" sent to %s', kv.get('title'), 'everyone' if kv.get('to') == 'all' else pid)
        return f'OK|Mail sent to {len(targets)} player(s).'
    if act == 'kick':
        if not sess:
            return 'ERR|Not online.'
        sess.w.close(); log.info('[admin] kicked %s', pid)
        return 'OK|Kicked.'
    if act in ('ban', 'unban'):
        _edit(server, pid, lambda st: st.__setitem__('banned', act == 'ban'))
        if act == 'ban' and sess:
            sess.w.close()
        log.info('[admin] %s %s', act, pid)
        return 'OK|' + ('Banned: they can no longer log in.' if act == 'ban' else 'Unbanned.')
    if act in ('mute', 'unmute'):
        _edit(server, pid, lambda st: st.__setitem__('muted', act == 'mute'))
        log.info('[admin] %s %s', act, pid)
        return 'OK|' + ('Muted: their chat is no longer sent to anyone.' if act == 'mute' else 'Unmuted.')
    if act == 'chatlog':
        rows = [c for c in CHAT if not pid or c[1] == pid][-300:]
        return 'OK|' + ('\n'.join(f'{time.strftime("%H:%M", time.localtime(t))} [{ch}] {n}: {tx}' for t, p, n, ch, tx in rows)
                        or '(no chat this session)')
    if act == 'delete':
        return _delete(server, pid, uid, log)
    if act == 'assignid':
        return _assign(server, pid, int(kv.get('new', 0) or 0), log)
    if act == 'reclaim':
        return _reclaim(server, pid, int(kv.get('official', 0) or 0), log)
    if act == 'stop':
        log.info('[admin] server stopping')
        import asyncio
        for sess in list(server.sessions.values()):   # save everyone and close their connection cleanly
            try:
                if sess.p:
                    sess.p.save()
                sess.w.close()
            except Exception:
                pass
        asyncio.get_event_loop().call_later(0.5, os._exit, 0)
        return 'OK|Stopping.'
    return 'ERR|unknown action ' + act


def _reclaim(server, pid, off, log):
    """A player who never backed up gets their old official id (and so their friends) back on a fresh account.
    Their old profile comes from any imported friend's saved friend list."""
    from game.player import _registry, _save_registry, LOCAL_ID_START
    if not off or off >= LOCAL_ID_START:
        return 'ERR|Enter their official player id.'
    if pid in server.sessions:
        return 'ERR|Ask the player to log out first.'
    if os.path.exists(os.path.join(ACC, f'{off}.json')):
        return 'ERR|That official id is already on this server.'
    reg = _registry()
    uid = next((u for u, p in reg['by_uid'].items() if p == pid), None)
    path = os.path.join(ACC, f'{pid}.json')
    if not uid or not os.path.exists(path):
        return 'ERR|Account not found.'
    st = json.load(open(path, encoding='utf-8'))
    if st.get('official_player_id'):
        return 'ERR|This account was imported from official already.'
    prof = None
    for p2, _, o in _accounts(server):   # someone who had them as a friend kept their profile
        prof = (o.get('social') or {}).get('profiles', {}).get(str(off)) or prof
    for k in ('player_id', 'channel_id'):
        if st.get(k) == pid:
            st[k] = off
    st['player_label'] = (prof or {}).get('playerLabel', off)
    st['official_player_id'] = off; st['reclaimed'] = True
    if prof and prof.get('nickName'):
        st['name'] = prof['nickName']
    json.dump(st, open(os.path.join(ACC, f'{off}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(path, path + f'.reclaimed_as_{off}')
    reg['by_uid'][uid] = off; _save_registry(reg)
    log.info('[admin] %s reclaimed official id %s (%s)', uid, off, st['name'])
    return f'OK|Done: now {st["name"]} (id {off}, UID {st["player_label"]}). Friends who imported see them again.'


def _remap(o, old, new):
    """Every reference to player `old` inside a save (dict keys like "123" or "9999:123", and number values) -> `new`."""
    so, sn = str(old), str(new)
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if isinstance(k, str):
                if k == so:
                    k = sn
                elif k.endswith(':' + so):
                    k = k[:-len(so)] + sn
            out[k] = _remap(v, old, new)
        return out
    if isinstance(o, list):
        return [_remap(v, old, new) for v in o]
    if o == old and isinstance(o, int) and not isinstance(o, bool):
        return new
    return o


# Parts of OTHER players' saves that point at someone: friends, requests, blocks, profiles, hearts, private chats.
_LINKS = (('social',), ('events', 'intimacy'), ('misc', 'private_chat'))


def _relink(server, old, new, log):
    """Point every other account's friends/requests/chats at the new id (new=None: drop them)."""
    n = 0
    for p2, _, _ in _accounts(server):
        if p2 in (old, new):
            continue

        def fix(st):
            hit = False
            for path in _LINKS:
                box = st
                for k in path[:-1]:
                    box = box.get(k) if isinstance(box, dict) else None
                if not isinstance(box, dict) or path[-1] not in box:
                    continue
                before = json.dumps(box[path[-1]], sort_keys=True)
                if new is None:
                    box[path[-1]] = _drop(box[path[-1]], old)
                else:
                    box[path[-1]] = _remap(box[path[-1]], old, new)
                hit = hit or json.dumps(box[path[-1]], sort_keys=True) != before
            if hit:
                fix.hit = True
        fix.hit = False
        _edit(server, p2, fix)
        n += fix.hit
    return n


def _drop(o, old):
    so = str(old)
    if isinstance(o, dict):
        return {k: _drop(v, old) for k, v in o.items() if k != so}
    if isinstance(o, list):
        return [_drop(v, old) for v in o if v != old]
    return o


def _delete(server, pid, uid, log):
    """Test accounts: the save is moved to save/deleted (not destroyed). Logging in with that account again starts fresh."""
    from game.player import _registry, _save_registry, _lock
    from rozefield_server import _pw_load, PW_FILE
    path = os.path.join(ACC, f'{pid}.json')
    if not pid or not os.path.exists(path):
        return 'ERR|Account not found.'
    if pid in server.sessions:
        server.sessions[pid].w.close()
        return 'ERR|They were online, so they have been kicked. Press Delete again in a few seconds.'
    st = json.load(open(path, encoding='utf-8'))
    gone = os.path.join(HERE, 'save', 'deleted'); os.makedirs(gone, exist_ok=True)
    with _lock:
        reg = _registry()
        for u, p in list(reg['by_uid'].items()):
            if p == pid:
                reg['by_uid'].pop(u)
        _save_registry(reg)
        os.replace(path, os.path.join(gone, f'{pid}_{time.strftime("%Y%m%d_%H%M%S")}.json'))
    if uid:
        d = _pw_load()
        if d.pop(uid, None) is not None:
            json.dump(d, open(PW_FILE, 'w', encoding='utf-8'))
        if server.login_keys.pop(uid, None):
            server.save_login_keys()
    n = _relink(server, pid, None, log)
    log.info('[admin] deleted account %s (%s); removed from %d other account(s)', pid, st.get('name'), n)
    return (f'OK|Deleted {st.get("name")} (id {pid}). Logging in with that account again makes a fresh character. '
            f'The old save is kept in save\\deleted in case you need it back.')


def _assign(server, pid, new, log):
    """Give a player another id (the UID shown in game). Friends, requests and chats on this server follow them."""
    from game.player import _registry, _save_registry, _lock
    path = os.path.join(ACC, f'{pid}.json')
    if not pid or not os.path.exists(path):
        return 'ERR|Account not found.'
    if not (1 <= new <= 2147483647):
        return 'ERR|Type a number from 1 to 2147483647.'
    if new == pid:
        return 'ERR|That is already their id.'
    if pid in server.sessions:
        return 'ERR|Ask the player to log out first (or Kick them).'
    if os.path.exists(os.path.join(ACC, f'{new}.json')) or any(
            new in (p2, o.get('player_label'), o.get('official_player_id')) for p2, _, o in _accounts(server) if p2 != pid):
        return f'ERR|Id {new} is taken by another player.'
    with _lock:
        reg = _registry()
        if new in reg['by_uid'].values():
            return f'ERR|Id {new} is taken by another player.'
        st = json.load(open(path, encoding='utf-8'))
        for k in ('player_id', 'channel_id'):
            if st.get(k) == pid:
                st[k] = new
        st['player_label'] = new           # the UID shown in game (imported accounts showed their official one)
        for k in ('pos_by_scene',):        # own garden positions are keyed "9999:<id>"
            if isinstance(st.get(k), dict):
                st[k] = {(kk[:-len(str(pid))] + str(new) if isinstance(kk, str) and kk.endswith(':' + str(pid)) else kk): v
                         for kk, v in st[k].items()}
        json.dump(st, open(os.path.join(ACC, f'{new}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(path, path + f'.moved_to_{new}')
        for u, p in list(reg['by_uid'].items()):
            if p == pid:
                reg['by_uid'][u] = new
        _save_registry(reg)
    n = _relink(server, pid, new, log)
    log.info('[admin] %s (%s) now has id %s; %d other account(s) updated', pid, st.get('name'), new, n)
    return f'OK|{st.get("name")} now has id {new}. Friends, requests and chats moved with them ({n} other account(s) updated).'
