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
