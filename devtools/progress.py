"""Rebuild the progress picture and checklist: docs/progress.svg + docs/PROGRESS.md.

    py tools/progress.py

Statuses come from docs/checklist.json (edit it when something changes); the bars are measured from the code:
  * client requests with a server handler        (proto/msgids.json vs game.handlers.H)
  * requests seen in real play that are handled  (official capture + local traffic.jsonl, cached in docs/progress_data.json)
  * quest steps with an event rule               (quest tables; needs data-merged/, cached otherwise)
Overall = average of the areas; area = average of its rows (done 1, partial 0.5, blocked/open 0, bars = fraction).
"""
import json, os, sys, time
from xml.sax.saxutils import escape
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # devtools package

GREEN, YELLOW, RED, GREY = '#4caf37', '#e8b20e', '#e5484d', '#2a2d36'
BG, FG, DIM, LINE = '#0d0e12', '#eceef2', '#9aa0ab', '#2a2d36'
STATE = {'done': (1.0, GREEN, 'done'), 'partial': (0.5, YELLOW, 'in progress'), 'blocked': (0.0, RED, 'blocked'),
         'open': (0.0, GREY, 'not yet')}


def measure():
    cache_f = os.path.join(DOCS, 'progress_data.json')
    cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
    from game.handlers import H
    ids = json.load(open(os.path.join(HERE, 'proto', 'msgids.json')))
    reqs = sorted(v for v in ids.values() if v.endswith('Req'))
    m = {'requests_total': len(reqs), 'requests_handled': sum(1 for r in reqs if r in H)}
    seen = set(cache.get('seen_requests', []))
    tl = os.path.join(HERE, 'traffic.jsonl')
    if os.path.exists(tl):
        for line in open(tl, encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('dir') == 'C2S':
                seen.add(r['name'])
    seen -= {'PlayerSceneRecordReq', 'PlayerPingReq'}
    m['seen_requests'] = sorted(seen)
    m['seen_total'], m['seen_handled'] = len(seen), sum(1 for r in seen if r in H)
    m['seen_missing'] = sorted(r for r in seen if r not in H)
    try:
        from game.data import Data
        from game import quests as Q
        d = Data()
        x = Q.idx(d)
        exact_types = set(Q.EVENT_TYPES)
        cells = []
        for q in sorted(x['quests']):
            for aid in Q.conditions_of(d, q):
                a = x['ach'].get(aid) or {}
                t = a.get('NewAchieveCondition')
                cells.append('exact' if t in exact_types else 'none' if t in Q.UNBUILT_TYPES or not a.get('Param') else 'reported')
        m['quest_cells'] = cells
        m['main_total'] = len(x['main_order'])
    except Exception as e:  # no game data here: use the cached numbers
        print('quest tables not available (%s): using cached quest numbers' % e.__class__.__name__)
        m['quest_cells'] = cache.get('quest_cells', [])
        m['main_total'] = cache.get('main_total', 648)
    json.dump({k: m[k] for k in ('seen_requests', 'quest_cells', 'main_total')}, open(cache_f, 'w'))
    return m


def rows_of(cfg, m):
    """-> areas: [(name, [(label, value 0..1, color, right_text, note, kind, stage)])]"""
    qc = m['quest_cells']
    ex, rep = qc.count('exact'), qc.count('reported')
    auto = cfg['story_autorun']
    bars = {
        '@requests_handled': ('Client requests with a server handler', m['requests_handled'], m['requests_total']),
        '@requests_seen': ('Requests seen in real play that are handled', m['seen_handled'], m['seen_total']),
        '@quest_steps': ('Quest steps with an event rule', ex + rep, len(qc) or 1),
        '@story_autorun': ('Main story quests cleared by an automated new account', auto['reached'], m['main_total']),
    }
    out = []
    for area in cfg['areas']:
        rows = []
        for r in area['rows']:
            label, st = r[0], r[1]
            note = r[2] if len(r) > 2 else ''
            stage = r[3] if len(r) > 3 else ('done' if st == 'done' else '')
            if st == 'bar':
                lab, a, b = bars[label]
                v = a / b if b else 0
                rows.append((lab, v, GREEN if v >= 0.999 else YELLOW, f'{v * 100:.2f}% {a:,}/{b:,}', note, 'bar', 'done' if v >= 0.999 else 'in progress'))
            else:
                v, col, txt = STATE[st]
                rows.append((label, v, col, txt, note, st, stage))
        out.append((area['name'], rows))
    return out


def svg(cfg, m, areas):
    W, pad = 1370, 28
    y = 0
    parts = []

    def text(x, yy, s, size=17, fill=FG, weight=400, anchor='start', mono=False):
        fam = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" if mono else "Inter,Segoe UI,Helvetica,Arial,sans-serif"
        parts.append(f'<text x="{x}" y="{yy}" font-family="{fam}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
                     f'text-anchor="{anchor}">{escape(s)}</text>')

    def segbar(x, yy, w, v, col, n=40, h=12):
        sw = w / n
        on = round(v * n) if v < 1 else n
        if 0 < v and on == 0:
            on = 1
        for i in range(n):
            parts.append(f'<rect x="{x + i * sw:.1f}" y="{yy}" width="{sw - 2:.1f}" height="{h}" rx="1" fill="{col if i < on else GREY}"/>')

    area_vals = [sum(r[1] for r in rows) / len(rows) for _, rows in areas]
    overall = sum(area_vals) / len(area_vals)
    y = 56
    text(pad, y, cfg['title'], 32, weight=600)
    text(W - pad, y, f'Overall {overall * 100:.2f}%', 32, weight=600, anchor='end', mono=True)
    y += 26
    segbar(pad, y, W - 2 * pad, overall, YELLOW, n=110, h=14)
    y += 40
    text(pad, y, ' · '.join(f'{n} {v * 100:.1f}%' for (n, _), v in zip(areas, area_vals)), 18, DIM)
    y += 26
    text(pad, y, 'Overall = average of the areas; each area = average of its rows (done 1, in progress 0.5, blocked / not yet 0; bars = fraction).', 15, DIM)
    y += 24
    text(pad, y, cfg['subtitle'] + '  Updated ' + time.strftime('%Y-%m-%d') + ' by devtools/progress.py.', 15, DIM)
    y += 34
    x = pad
    for col, lab in ((GREEN, 'done'), (YELLOW, 'in progress / partial'), (RED, 'blocked'), (GREY, 'not yet')):
        parts.append(f'<rect x="{x}" y="{y - 13}" width="14" height="14" fill="{col}"/>')
        text(x + 22, y, lab, 17)
        x += 60 + len(lab) * 9
    y += 26
    for (name, rows), v in zip(areas, area_vals):
        y += 52
        text(pad, y, name, 22, weight=600)
        text(W - pad, y, f'{v * 100:.1f}%', 22, weight=600, anchor='end', mono=True)
        y += 14
        parts.append(f'<line x1="{pad}" y1="{y}" x2="{W - pad}" y2="{y}" stroke="{LINE}"/>')
        y += 14
        for label, val, col, right, note, kind, stage in rows:
            y += 29
            text(pad, y, label, 17)
            if note and kind != 'bar':
                text(728, y, note, 15, DIM)
            if kind == 'bar':
                segbar(700, y - 12, 460, val, col)
            else:
                parts.append(f'<rect x="700" y="{y - 13}" width="14" height="14" rx="2" fill="{col}"/>')
            rtxt = stage if (name == 'Gameplay' and stage and kind != 'bar' and kind != 'done') else right
            text(W - pad, y, rtxt, 16, DIM if kind != 'bar' else FG, anchor='end', mono=True)
    # quest step grid
    qc = m['quest_cells']
    if qc:
        y += 50
        ex, rep, none = qc.count('exact'), qc.count('reported'), qc.count('none')
        text(pad, y, f'Quest steps: {ex + rep:,} of {len(qc):,} have a rule ({(ex + rep) / len(qc) * 100:.1f}%)', 22, weight=600)
        y += 14
        parts.append(f'<line x1="{pad}" y1="{y}" x2="{W - pad}" y2="{y}" stroke="{LINE}"/>')
        y += 28
        text(pad, y, 'One cell per quest step in the client tables. Green = the server tracks that action; grey = needs a system not built yet (life skills, gathering, dungeons...).', 15, DIM)
        y += 16
        cols, cw = 56, 20
        gx = pad
        for i, c in enumerate(sorted(qc, key=lambda c: {'exact': 0, 'reported': 1, 'none': 2}[c])):
            r, k = divmod(i, cols)
            parts.append(f'<rect x="{gx + k * cw}" y="{y + r * cw}" width="{cw - 3}" height="{cw - 3}" fill="'
                         f'{GREEN if c == "exact" else YELLOW if c == "reported" else GREY}"/>')
        lx = gx + cols * cw + 24
        leg = [(c, l) for c, l, n in ((GREEN, f'{ex:,} exact', ex), (YELLOW, f'{rep:,} reported', rep), (GREY, f'{none:,} no rule yet', none)) if n]
        for j, (col, lab) in enumerate(leg):
            parts.append(f'<rect x="{lx}" y="{y + 6 + j * 34}" width="16" height="16" fill="{col}"/>')
            text(lx + 26, y + 21 + j * 34, lab, 17)
        y += ((len(qc) + cols - 1) // cols) * cw + 20
    H = y + 20
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<rect width="{W}" height="{H}" fill="{BG}"/>' + ''.join(parts) + '</svg>'), overall


def _prev_line(cfg, overall):
    prev = cfg.get('previous')
    if not prev:
        return ''
    now_pct = round(overall * 100, 2)
    diff = now_pct - float(prev['overall'])
    sign = '+' if diff >= 0 else ''
    return f'**Before ({prev["date"]}):** {prev["overall"]:.2f}% → **After ({time.strftime("%Y-%m-%d")}):** {now_pct:.2f}% (`{sign}{diff:.2f}%`)'


def markdown(cfg, m, areas, overall):
    out = [f'# {cfg["title"]}: {overall * 100:.2f}%', '', '![progress](progress.png)', '']
    pl = _prev_line(cfg, overall)
    if pl:
        out += [pl, '']
    out += [f'_{cfg["subtitle"]} Updated {time.strftime("%Y-%m-%d")}; regenerate with `py devtools/progress.py`._', '']
    mark = {'done': '[x]', 'partial': '[~]', 'blocked': '[!]', 'open': '[ ]', 'bar': '[~]'}
    for name, rows in areas:
        v = sum(r[1] for r in rows) / len(rows)
        out += [f'## {name} ({v * 100:.1f}%)', '']
        for label, val, col, right, note, kind, stage in rows:
            m_ = '[x]' if kind == 'bar' and val >= 0.999 else mark[kind]
            extra = f' ({right})' if kind == 'bar' else ''
            st_tag = f' [`{stage}`]' if name == 'Gameplay' and stage and kind != 'done' and kind != 'bar' else ''
            out.append(f'- {m_} {label}{extra}{st_tag}' + (f': {note}' if note else ''))
        out.append('')
    out += ['Legend: `[x]` done, `[~]` in progress (`test` / `retest` / `captured`), `[!]` blocked, `[ ]` not yet.', '']
    if m['seen_missing']:
        out += ['Requests seen in play that still get an empty answer: ' + ', '.join(f'`{r}`' for r in m['seen_missing']), '']
    return '\n'.join(out)


SQ = {'done': '🟩', 'partial': '🟨', 'blocked': '🟥', 'open': '⬛'}


def bar(v, n=30):
    k = round(v * n)
    return '▰' * k + '▱' * (n - k)


def readme(cfg, m, areas, overall):
    """Front page of the repo: the progress chart drawn in text (shows even where images are blocked)."""
    area_vals = [sum(r[1] for r in rows) / len(rows) for _, rows in areas]
    pl = _prev_line(cfg, overall)
    out = [f'# {cfg["title"]} — {overall * 100:.2f}%', '', f'`{bar(overall, 40)}` **{overall * 100:.2f}%**', '']
    if pl:
        out += [pl, '']
    out += [cfg['subtitle'], '', '## The three parts', '',
           '| Part | What it is | Get it |', '|---|---|---|',
           '| **Overfield** | The game. Not shared here (it belongs to its makers): use your own copy (Steam or the OverField launcher) '
           'and point it at a server with Overfield Backup, or the game package your server owner gives you | your own install |',
           '| **Overfield Backup** (by RozenCrimsonvale) | Save your official account before 8 Feb 2027; **Play on Rozefield** points your '
           'own game at a server (a copy, or the game itself) | [Releases](https://github.com/Erorodata/Rozefield/releases/latest): `Overfield-Backup.zip` |',
           '| **Overfield Server** (by RozenCrimsonvale) | Host a server: control panel with a setup wizard, sharing, traffic, '
           'imports, moving to another device; Windows, Linux or a VPS | [Releases](https://github.com/Erorodata/Rozefield/releases/latest): `Overfield-Server.zip` |', '',
           '| Area | Progress | |', '|---|---|---:|']
    for (name, _), v in zip(areas, area_vals):
        out.append(f'| {name} | `{bar(v)}` | **{v * 100:.1f}%** |')
    out += ['', '🟩 done · 🟨 in progress (`test` / `retest` / `captured`) · 🟥 blocked · ⬛ not yet', '']
    for (name, rows), v in zip(areas, area_vals):
        if name == 'Gameplay':
            out += [f'## {name} — {v * 100:.1f}%', '', '| | Item | Stage | Status |', '|---|---|---|---|']
            for label, val, col, right, note, kind, stage in rows:
                if kind == 'bar':
                    out.append(f'| {"🟩" if val >= 0.999 else "🟨"} | {label} | `done` | `{bar(val, 20)}` {right} |')
                else:
                    st_cell = f'`{stage}`' if stage else f'`{right}`'
                    out.append(f'| {SQ[kind]} | {label} | {st_cell} | {right}{" — " + note if note else ""} |')
        else:
            out += [f'## {name} — {v * 100:.1f}%', '', '| | Item | Status |', '|---|---|---|']
            for label, val, col, right, note, kind, stage in rows:
                if kind == 'bar':
                    out.append(f'| {"🟩" if val >= 0.999 else "🟨"} | {label} | `{bar(val, 20)}` {right} |')
                else:
                    out.append(f'| {SQ[kind]} | {label} | {right}{" — " + note if note else ""} |')
        out.append('')
    qc = m['quest_cells']
    if qc:
        ex = len([c for c in qc if c != 'none'])
        out += [f'**Quest steps with a rule:** {ex:,} / {len(qc):,} (`{bar(ex / len(qc))}` {ex / len(qc) * 100:.1f}%)', '']
    out += ['![Rozefield progress chart](docs/progress.png)', '',
            f'_Updated {time.strftime("%Y-%m-%d")} by `py devtools/progress.py` from [docs/checklist.json](docs/checklist.json)._', '',
            '## About', '',
            'Rozefield preserves OverField: the archived client and a private server that runs it after the official shutdown.', '',
            '- [Archive notes: client build, endpoints, protocol, captures](docs/ARCHIVE.md)',
            '- [Server: setup, login window, backup / import, GM commands](server/README.md)',
            '- [Host your own server](docs/HOSTING.md)',
            '- [Checklist (plain)](docs/PROGRESS.md)', '']
    return '\n'.join(out)


def main():
    cfg = json.load(open(os.path.join(DOCS, 'checklist.json'), encoding='utf-8'))
    m = measure()
    areas = rows_of(cfg, m)
    s, overall = svg(cfg, m, areas)
    open(os.path.join(DOCS, 'progress.svg'), 'w', encoding='utf-8').write(s)
    try:  # GitHub's file viewer can refuse inline SVG; the README shows the PNG
        import cairosvg
        cairosvg.svg2png(bytestring=s.encode('utf-8'), write_to=os.path.join(DOCS, 'progress.png'))
    except Exception as e:
        print('progress.png not updated (pip install cairosvg):', e.__class__.__name__)
    open(os.path.join(DOCS, 'PROGRESS.md'), 'w', encoding='utf-8').write(markdown(cfg, m, areas, overall))
    open(os.path.join(ROOT, 'README.md'), 'w', encoding='utf-8').write(readme(cfg, m, areas, overall))
    print(f'overall {overall * 100:.2f}% -> docs/progress.svg, docs/PROGRESS.md')


if __name__ == '__main__':
    main()
