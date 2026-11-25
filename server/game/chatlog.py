"""Chat history kept across logins and server restarts (save/chat.json).

Official: after entering a scene channel the server sends ChatMsgRecordInitNotice with that channel's recent
lines (nearby chat), and at login the recent world-chat lines. Private chat is kept in each player's save.
"""
import json, os, threading

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'save', 'chat.json')
KEEP = 50
_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is None:
        try:
            _data = json.load(open(PATH, encoding='utf-8'))
        except (OSError, ValueError):
            _data = {}
        _data.setdefault('world', [])
        _data.setdefault('channels', {})
    return _data


def _save():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, PATH)


def world():
    with _lock:
        return list(_load()['world'])


def channel(scene_id, channel_id):
    with _lock:
        return list(_load()['channels'].get(f'{scene_id}:{channel_id}', []))


def add_world(msg):
    with _lock:
        w = _load()['world']
        w.append(msg)
        del w[:-KEEP]
        _save()


def add_channel(scene_id, channel_id, msg):
    with _lock:
        c = _load()['channels'].setdefault(f'{scene_id}:{channel_id}', [])
        c.append(msg)
        del c[:-KEEP]
        _save()
