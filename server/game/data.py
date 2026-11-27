"""Game data tables (extracted from the client's PBStaticConfigure bundle by tools/extract_config.py)."""
import json, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(HERE, 'data-merged') if os.path.exists(os.path.join(HERE, 'data-merged')) or os.path.exists(os.path.join(HERE, 'data-merged.zip')) else os.path.join(HERE, 'data')


class Data:
    def __init__(self, path=DATA_DIR):
        self.path = path
        self._raw = {}
        self._idx = {}
        z = path.rstrip('/\\') + '.zip'
        stamp = os.path.join(path, '.from_zip')
        if os.path.exists(z) and (not os.path.exists(stamp) or os.path.getmtime(z) > os.path.getmtime(stamp)):
            import zipfile  # (re)extract when the shipped zip is newer than the extracted copy
            zf = zipfile.ZipFile(z)
            top = os.path.basename(path.rstrip('/\\')) + '/'
            zf.extractall(os.path.dirname(path.rstrip('/\\')) if all(n.startswith(top) for n in zf.namelist()) else path)
            open(stamp, 'w').close()
        if not os.path.isdir(path) or not os.listdir(path):
            raise SystemExit(f'No game data in {path}. Run: py tools\\extract_config.py "<game>\\launcher_Data\\yoo"')
        from ofproto import pool
        self._tags = {v.number: v.name for v in pool.FindEnumTypeByName('pb.EBagItemTag').values}

    def raw(self, f):
        if f not in self._raw:
            p = os.path.join(self.path, f + '.json')
            self._raw[f] = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
            from game import packs   # host content packs add to / change the official tables
            packs.apply(f, self._raw[f])
        return self._raw[f]

    def table(self, f, sheet):
        """{ID: row} for one sheet of one table file."""
        k = (f, sheet)
        if k not in self._idx:
            rows = self.raw(f).get(sheet, {}).get('datas', [])
            self._idx[k] = {r.get('ID', 0): r for r in rows}
        return self._idx[k]

    def row(self, f, sheet, id_):
        return self.table(f, sheet).get(id_)

    def config(self, key, default=None):
        for r in self.table('globalconfig', 'Config').values():
            if r.get('Key') == key:
                return r.get('Values', [])
        return default

    def config_int(self, key, default=0, i=0):
        v = self.config(key)
        try:
            return int(v[i])
        except Exception:
            return default

    # ---- items
    def item(self, item_id):
        return self.row('item', 'Item', item_id)

    def item_tag(self, item_id):
        if 1070000 <= int(item_id) < 1080000:
            return 'EBagItemTag_Weapon'   # Rozefield Shovel-slot Umbrella Tool (1070000 + umbrella_id)
        r = self.item(item_id)
        return self._tags.get((r or {}).get('NewBagItemTag', 0), 'EBagItemTag_None')

    def reward_items(self, pool_id, level=1, rng=None):
        """Expand a RewardPool id into [(item_id, count)] following the table's min/max counts."""
        import random
        rng = rng or random
        out = []
        rp = self.row('reward', 'RewardPool', pool_id)
        if not rp:
            return out
        for g in rp.get('RewardPoolGroup', []):
            ip = self.row('reward', 'RewardItemPool', g.get('RewardPoolGroupID'))
            if not ip:
                continue
            for it in ip.get('RewardItemPoolGroup', []):
                if not (it.get('MinLevelLimit', 1) <= level <= it.get('MaxLevelLimit', 999)):
                    continue
                rate = it.get('ItemRate', 1.0)
                if rate < 1.0 and rng.random() > rate:
                    continue
                n = rng.randint(it.get('ItemMinCount', 1), max(it.get('ItemMinCount', 1), it.get('ItemMaxCount', 1)))
                if n > 0:
                    out.append((it['ItemID'], n))
        return out
