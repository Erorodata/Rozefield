"""Traffic counters for the panel's Traffic card: data to / from players, messages, downloads (game updates and the
game package), per player, the last 10 minutes and today.

    record('down'|'up', nbytes, who=name, msgs=n)     game connections
    record('dl', nbytes)                              file downloads (updates, Rozefield.zip)
    text()  ->  rate|down B/s|up B/s|msgs/s|today bytes|downloads B/s
                hist|d,u,m;...      60 buckets of 10 s (oldest first), bytes and messages per second
                p|name|down B/s|up B/s|msgs/s     one line per player seen in the last 10 s
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY_FILE = os.path.join(HERE, 'save', 'traffic_today.json')
_lock = threading.Lock()
_sec = {}            # second -> [down, up, msgs, dl]
_who = {}            # name -> {second: [down, up, msgs]}
_today = {'day': '', 'bytes': 0}
_saved_at = 0


def _load_today():
    try:
        _today.update(json.load(open(TODAY_FILE, encoding='utf-8')))
    except Exception:
        pass


_load_today()


def record(kind, n, who=None, msgs=0):
    now = int(time.time())
    day = time.strftime('%Y-%m-%d')
    with _lock:
        b = _sec.setdefault(now, [0, 0, 0, 0])
        i = {'down': 0, 'up': 1, 'dl': 3}[kind]
        b[i] += n
        b[2] += msgs
        if who and kind != 'dl':
            w = _who.setdefault(who, {}).setdefault(now, [0, 0, 0])
            w[i] += n
            w[2] += msgs
        if _today['day'] != day:
            _today.update(day=day, bytes=0)
        _today['bytes'] += n
    _maybe_trim(now)


def _maybe_trim(now):
    global _saved_at
    if now - _saved_at < 60:
        return
    _saved_at = now
    with _lock:
        for s in [s for s in _sec if s < now - 660]:
            del _sec[s]
        for name in list(_who):
            d = _who[name]
            for s in [s for s in d if s < now - 30]:
                del d[s]
            if not d:
                del _who[name]
        snap = dict(_today)
    try:
        os.makedirs(os.path.dirname(TODAY_FILE), exist_ok=True)
        json.dump(snap, open(TODAY_FILE, 'w', encoding='utf-8'))
    except OSError:
        pass


def text():
    now = int(time.time())
    with _lock:
        last = [_sec.get(s, [0, 0, 0, 0]) for s in range(now - 10, now)]
        rate = [sum(x[i] for x in last) // 10 for i in range(4)]
        hist = []
        for k in range(60):
            start = now - 600 + k * 10
            sl = [_sec.get(s, [0, 0, 0, 0]) for s in range(start, start + 10)]
            hist.append(','.join(str(sum(x[i] for x in sl) // 10) for i in range(3)))
        players = []
        for name, d in _who.items():
            sl = [d.get(s, [0, 0, 0]) for s in range(now - 10, now)]
            r = [sum(x[i] for x in sl) // 10 for i in range(3)]
            if any(r):
                players.append(f'p|{name.replace("|", "/")}|{r[0]}|{r[1]}|{r[2]}')
        today = _today['bytes'] if _today['day'] == time.strftime('%Y-%m-%d') else 0
    return '\n'.join([f'rate|{rate[0]}|{rate[1]}|{rate[2]}|{today}|{rate[3]}', 'hist|' + ';'.join(hist)] + sorted(players))
