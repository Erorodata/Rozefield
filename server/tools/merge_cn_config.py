"""Merge CN-only data table rows into the Global data tables and rebuild the Global PBStaticConfigure bundle.

    py tools\\merge_cn_config.py <global_config_bundle __data> <global data dir> <cn data dir> <translations.json> <out_bundle>

* every sheet: Global rows kept as-is, CN rows whose ID Global lacks are appended
* string tables: CN-only text rows go into every Global language table; English/Japanese/Korean use
  translations.json ({"<Sheet>:<ID>": ["text", ...]}) when present, Traditional Chinese is converted
* tables the Global client has no schema for (e.g. Exploration) are skipped
Also writes <global data dir>-merged/ with the merged JSON for the server.
"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

SKIP_FILES = {'exploration'}
CONFIG_OVERRIDES = {k: '500000' for k in ('HomeItemPointMax', 'PublicHomeItemPointMax', 'PrivateHomeItemPointMax',
                                               'SpecialPublicHomeItemPointMax')}
CONFIG_OVERRIDES.update({'Player_Friend_Count': '9999', 'Player_Friend_Apply_Count': '9999'})   # no friend limit on Rozefield
LANG_FALLBACK = {'english': 'en', 'japanese': 'en', 'korea': 'en', 'traditional': 'tc', 'simplified': 'sc'}


def rkey(r):
    return r.get('ID', json.dumps(r, sort_keys=True, ensure_ascii=False))


UI_TR = {}
_uitr = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cn_ui_translations_en.json')
if os.path.exists(_uitr):
    UI_TR = json.load(open(_uitr, encoding='utf-8'))
LANG_COLS = ('English', 'Japanese', 'Korea')


def _placeholder(t):
    return not t or t.startswith('_') or any(t.endswith('_' + c) for c in LANG_COLS + ('Traditional',))


def fix_ui_text(r, cc):
    """CN-only UI label: fill the English/Japanese/Korean columns (CN builds leave '<zh>_English' placeholders)."""
    zh = r.get('Chinese_Simplified', '')
    en = UI_TR.get('UIStaticText', {}).get(r.get('Key')) or UI_TR.get('UIStaticText', {}).get(zh)
    for col in LANG_COLS:
        if _placeholder(r.get(col, '')):
            r[col] = en or zh
    if _placeholder(r.get('Chinese_Traditional', '')):
        r['Chinese_Traditional'] = cc.convert(zh) if cc and zh else zh


def fix_dialog(r, lang):
    if lang in ('english', 'japanese', 'korea'):
        r['Content'] = UI_TR.get('StringDialogText', {}).get(r.get('Key'), r.get('Content', ''))
        r['Title'] = UI_TR.get('Titles', {}).get(r.get('Title'), r.get('Title', ''))


def merge_sheets(g, c, string_lang=None, tr=None, cc=None):
    added = 0
    for sh, v in c.items():
        if not isinstance(v, dict) or 'datas' not in v:
            continue
        gv = g.setdefault(sh, {'datas': []})
        have = {rkey(r) for r in gv.get('datas', [])}
        keys = {r['Key'] for r in gv.get('datas', []) if isinstance(r.get('Key'), str) and r.get('Key')}
        for r in v['datas']:
            # CN renumbered many rows: same Key under a new ID would shadow the Global (English) row
            if not r or rkey(r) in have or (isinstance(r.get('Key'), str) and r.get('Key') in keys):
                continue
            r = json.loads(json.dumps(r))
            have.add(rkey(r))
            if isinstance(r.get('Key'), str):
                keys.add(r['Key'])
            if sh == 'UIStaticText':
                fix_ui_text(r, cc)
            if string_lang and 'Content' in r:
                fix_dialog(r, string_lang)
            if string_lang and 'Text' in r:
                mode = LANG_FALLBACK.get(string_lang, 'en')
                if mode == 'en' and tr and f'{sh}:{r.get("ID", 0)}' in tr:
                    r['Text'] = tr[f'{sh}:{r.get("ID", 0)}']
                elif mode == 'tc' and cc:
                    r['Text'] = [cc.convert(t) for t in r['Text']]
            gv.setdefault('datas', []).append(r)
            added += 1
    return added


def main():
    rewrite_all = '--rewrite-all' in sys.argv  # base bundle already merged once: re-serialize every table
    bundle, gdir, cdir, trf, out = [a for a in sys.argv[1:] if not a.startswith('--')][:5]
    import UnityPy
    from google.protobuf import descriptor_pb2, message_factory, json_format
    from ofproto import pool
    try:
        from opencc import OpenCC
        cc = OpenCC('s2t')
    except Exception:
        cc = None
    tr = json.load(open(trf, encoding='utf-8')) if os.path.exists(trf) else {}
    fds = descriptor_pb2.FileDescriptorSet(); fds.ParseFromString(open(os.path.join(HERE, 'proto', 'overfield.desc'), 'rb').read())
    tops = {m.name[3:-5].lower(): fd.package + '.' + m.name for fd in fds.file for m in fd.message_type
            if m.name.startswith('All') and m.name.endswith('Datas')}
    mdir = gdir.rstrip('/\\') + '-merged'
    os.makedirs(mdir, exist_ok=True)
    env = UnityPy.load(bundle)
    total = 0
    cn_simpl = json.load(open(os.path.join(cdir, 'string_simplified.json'), encoding='utf-8'))
    for path_, obj in env.container.items():
        if obj.type.name != 'TextAsset':
            continue
        base = os.path.basename(path_)[:-6]
        name = tops.get(base.replace('_', '')) or tops.get(base.lower()) or tops.get(base.split('_')[0])
        gj = os.path.join(gdir, base + '.json')
        if not name or not os.path.exists(gj) or base in SKIP_FILES:
            continue
        g = json.load(open(gj, encoding='utf-8'))
        if base.startswith('string_'):
            lang = base.split('_', 1)[1]
            n = merge_sheets(g, cn_simpl, lang, tr, cc)
        elif os.path.exists(os.path.join(cdir, base + '.json')):
            n = merge_sheets(g, json.load(open(os.path.join(cdir, base + '.json'), encoding='utf-8')))
        else:
            n = 0
        if base == 'globalconfig':  # Rozefield: raise the plaza ornament point caps
            for r in g.get('Config', {}).get('datas', []):
                if r.get('Key') in CONFIG_OVERRIDES:
                    r['Values'] = [CONFIG_OVERRIDES[r['Key']]]
                    n += 1
        json.dump(g, open(os.path.join(mdir, base + '.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        if not n and not (rewrite_all and os.path.exists(os.path.join(cdir, base + '.json'))):
            continue
        m = message_factory.GetMessageClass(pool.FindMessageTypeByName(name))()
        json_format.ParseDict(g, m, ignore_unknown_fields=True)
        t = obj.read()
        t.m_Script = m.SerializeToString().decode('utf-8', 'surrogateescape')
        t.save()
        total += n
        print(f'{base}: +{n} rows')
    for f in os.listdir(gdir):  # carry over untouched tables
        if os.path.isfile(os.path.join(gdir, f)) and not os.path.exists(os.path.join(mdir, f)):
            import shutil
            shutil.copy(os.path.join(gdir, f), os.path.join(mdir, f))
    open(out, 'wb').write(env.file.save(packer='lz4'))
    print(f'{total} rows added -> {out}')


if __name__ == '__main__':
    main()
