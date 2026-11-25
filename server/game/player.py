"""Player account state: creation, inventory, persistence.

State is a plain JSON dict (save/accounts/<uid>.json) so it can be inspected or edited by hand.
"""
import copy, json, os, random, threading, time
import logging
log = logging.getLogger("rozefield")

INSTANCE_TAGS = {  # item tags that are unique instances, stored per instance id
    'EBagItemTag_Weapon': 'weapons', 'EBagItemTag_Armor': 'armors', 'EBagItemTag_Poster': 'posters',
    'EBagItemTag_Pet': 'pets',
}
SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'save', 'accounts')
_REG = os.path.join(SAVE_DIR, '_registry.json')
_lock = threading.Lock()


# Player ids. Imported accounts keep their OFFICIAL id (official ids run from about 1,000,000 to 2,300,000 at
# shutdown), so friends find each other again. Accounts made on Rozefield get ids from LOCAL_ID_START up, a range
# the official game never reached, so a new player can never take an old player's id.
LOCAL_ID_START = 9000001


def _registry():
    if os.path.exists(_REG):
        r = json.load(open(_REG, encoding='utf-8'))
    else:
        r = {'next_player_id': LOCAL_ID_START, 'by_uid': {}}
    r['next_player_id'] = max(r.get('next_player_id', 0), LOCAL_ID_START)
    return r


def new_local_id(reg):
    """Next free Rozefield-made id (never an official one, never one already saved)."""
    used = set(reg['by_uid'].values())
    pid = max(reg['next_player_id'], LOCAL_ID_START)
    while pid in used or os.path.exists(os.path.join(SAVE_DIR, f'{pid}.json')):
        pid += 1
    reg['next_player_id'] = pid + 1
    return pid


def migrate_local_ids(log=print):
    """Accounts made on Rozefield before LOCAL_ID_START existed (ids 2,000,001+) could clash with official ids:
    move them into the local range. Imported accounts (with official_player_id) keep their ids."""
    with _lock:
        reg = _registry(); moved = 0
        for uid, pid in list(reg['by_uid'].items()):
            if not (2000000 < pid < LOCAL_ID_START):
                continue
            path = os.path.join(SAVE_DIR, f'{pid}.json')
            if not os.path.exists(path):
                continue
            st = json.load(open(path, encoding='utf-8'))
            if st.get('official_player_id'):
                continue
            new = new_local_id(reg)
            for k in ('player_id', 'player_label', 'channel_id'):
                if st.get(k) == pid:
                    st[k] = new
            json.dump(st, open(os.path.join(SAVE_DIR, f'{new}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
            os.replace(path, path + '.moved_to_%d' % new)
            reg['by_uid'][uid] = new; moved += 1
            log(f'account "{st.get("name")}" moved from id {pid} to {new} (Rozefield ids start at {LOCAL_ID_START})')
        if moved:
            _save_registry(reg)


def _save_registry(r):
    os.makedirs(SAVE_DIR, exist_ok=True)
    json.dump(r, open(_REG, 'w', encoding='utf-8'), indent=1)


FAREWELL_MAIL = {
    'mail_state': 'MailState_UNCLAIM', 'sender': 'The OverField Team', 'content_type': 'MailContentType_TEXT',
    'title': 'OverField Farewell Rewards',
    'content': ("Dear Leaders,\nAs previously announced, OverField will end service on February 8, 2027, at 23:59 (UTC+8). "
                "Until then, we'll be giving out a series of rewards.\nThank you for staying with us until the very end. These "
                "rewards are a small token of our appreciation, and we hope they help you enjoy OverField to the fullest before we "
                "say goodbye.\nThe OverField Team\nNovember 24, 2026\n"),
    'overdueDay': 9999,
    'items': [{'itemId': i, 'num': str(n)} for i, n in ((102, 100000), (125, 10000), (2020, 9999), (2050, 9999), (2051, 9999),
                                                       (2052, 9999), (2070, 9999), (2071, 9999), (2072, 9999), (2073, 9999),
                                                       (2074, 9999), (2080, 9999), (401, 999), (1502, 520))],
}


class Player:
    def __init__(self, data, state, path):
        self.d = data
        self.s = state
        self.path = path
        self.dirty = False
        self.migrate()

    def migrate(self):
        s = self.s
        from game import life
        life.migrate(self)
        if not s.get('farewell_mail'):   # every player gets the official Farewell Rewards letter, kept forever
            mails = s.setdefault('mails', [])
            have = next((m for m in mails if 'Farewell' in (m.get('title') or '')), None)
            if not have:
                have = dict(FAREWELL_MAIL, mail_id=max([m.get('mail_id', 0) for m in mails] + [1232]) + 1,
                            send_time=str(int(time.time())))
                mails.insert(0, have)
            have['overdueDay'] = 9999
            s['mail_keep'] = sorted(set(s.get('mail_keep', [])) | {have['mail_id']})
            s['farewell_mail'] = True
            self.dirty = True
        if 'chapters' not in s:  # saves made before story chapters were tracked: a story's reward is claimed once its quest is Finish
            s['chapters'] = {}
            chap = {sid: c['ID'] for c in self.d.table('story', 'StoryChapter').values() for sid in c.get('StoryList', [])}
            for st in self.d.table('story', 'Story').values():
                q = s.get('quests', {}).get(str(st.get('QuestID')))
                if q and q.get('status') == 'QuestStatus_Finish' and st['ID'] in chap:
                    s['chapters'].setdefault(str(chap[st['ID']]), []).append(st['ID'])
            self.dirty = True

    # ------------------------------------------------------------ load/create
    @classmethod
    def load_or_create(cls, data, uid, name=None):
        os.makedirs(SAVE_DIR, exist_ok=True)
        with _lock:
            reg = _registry()
            pid = reg['by_uid'].get(str(uid))
            if pid is None:
                pid = new_local_id(reg)
                reg['by_uid'][str(uid)] = pid; _save_registry(reg)
        path = os.path.join(SAVE_DIR, f'{pid}.json')
        if os.path.exists(path):
            p = cls(data, json.load(open(path, encoding='utf-8')), path)
            try:
                from tools.import_extras import backfill_from_backup, merge_world_files, backfill_placed
                changed = False
                if p.s.get('official_player_id') and not p.s.get('extras_imported'):
                    changed |= bool(backfill_from_backup(p.s, log.info))
                changed |= bool(merge_world_files(p.s, log.info))
                changed |= p.migrate_furniture_bag()
                changed |= bool(backfill_placed(p.s, log.info))
                if changed:
                    p.save()
            except Exception:
                log.exception('backfill from backup')
            return p
        p = cls(data, cls.new_state(data, uid, pid, name), path)
        p.s['furniture_bag_v2'] = True
        p.grant_initial()
        p.save()
        return p

    @staticmethod
    def new_state(d, uid, pid, name):
        now = int(time.time())
        return {
            'version': 1, 'uid': str(uid), 'player_id': pid, 'player_label': pid, 'name': name or f'Salvager{pid % 100000}',
            'create_time': now, 'last_login': 0, 'level': 1, 'exp': 0, 'world_level': 1, 'head': 0, 'sign': '',
            'phone_background': 0, 'phone_case': 0, 'birthday': '', 'sex': 0,
            'unlock_functions': [], 'characters': {}, 'team': {},
            'items': {},                     # stackable item id -> count
            'weapons': {}, 'armors': {}, 'posters': {}, 'pets': {}, 'outfits': {}, 'inscriptions': {},
            'next_instance': 1,
            'scene_id': d.config_int('Player_Initial_Scenario_ID', 100), 'channel_id': 0,
            'quests': {}, 'chapters': {}, 'tutorials': [],
            'garden': {'furniture': {}, 'likes': 0, 'access': 0, 'open': True, 'next_furniture_id': 1},
            'placed_characters': [], 'buffs': {}, 'gacha': {}, 'shop': {}, 'appearance': {},
            'gm': True,
        }

    def grant_initial(self):
        d = self.d
        for cid in d.config('Init_Character_IDs', ['101001']):
            self.add_character(int(cid))
        ids = list(self.s['characters'])
        if ids:
            self.s['team'] = {'char1': int(ids[0])}
        self.add_items(d.reward_items(d.config_int('InitialReward', 600)))
        umb = d.config_int('Player_Default_Umbrella_ItemID', 0)
        if umb:
            self.add_item(umb, 1)
        from game import quests
        q = d.config_int('InitialQuest', 0)
        if q:
            quests.accept(self, q)

    def save(self):
        self.s['saved_at'] = int(time.time())
        tmp = self.path + '.tmp'
        json.dump(self.s, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        os.replace(tmp, self.path)
        self.dirty = False

    # ------------------------------------------------------------ items
    def _next_iid(self):
        i = self.s['next_instance']; self.s['next_instance'] += 1
        return i

    def count(self, item_id):
        return int(self.s['items'].get(str(item_id), 0))

    def _daily_task(self):
        try:
            from game.events import _daily_task
            return _daily_task(self)
        except Exception:
            return {}

    def _player_buffs(self):
        import time as _t
        now = _t.time()
        lst = [{'buffId': int(b), 'endTime': str(int(e))} for b, e in self.s.get('buffs', {}).items() if e > now]
        life = {'systemType': 'BuffSystemType_LIFE'}
        if lst:
            life['buffLst'] = lst          # same list as the in-game buff notice (handlers.buff_list)
        return [life, {'systemType': 'BuffSystemType_GLOBAL'}]

    def furniture_used(self):
        """Pieces in use (placed in the own plaza or lifted in the hand). The bag keeps the owned total, as official."""
        used = {}
        for f in self.s['garden']['furniture'].values():
            used[f['furnitureItemId']] = used.get(f['furnitureItemId'], 0) + 1
        for h in self.s.get('handing', {}).values():
            if isinstance(h, dict) and h.get('lifted'):
                used[h['itemId']] = used.get(h['itemId'], 0) + 1
        return used

    def migrate_furniture_bag(self):
        """Older builds took a piece out of the bag when it was placed. Put pieces this server placed back into the
        bag once, so the bag is the owned total again (imported pieces were never taken out)."""
        s = self.s
        if s.get('furniture_bag_v2'):
            return False
        g = s['garden']
        base, top = s['player_id'] * 100000, s['player_id'] * 100000 + g.get('next_furniture_id', 1)
        for fid, f in g['furniture'].items():
            if str(fid).isdigit() and base <= int(fid) < top:
                self.add_item(f['furnitureItemId'], 1)
        for fid, h in s.get('handing', {}).items():
            if isinstance(h, dict) and h.get('lifted') and str(fid).isdigit() and base <= int(fid) < top:
                self.add_item(h['itemId'], 1)
        s['furniture_bag_v2'] = True
        return True

    def item_info(self, item_id, num=None):
        """ItemInfo dict for a stackable item showing its current total (or num)."""
        tag = self.d.item_tag(item_id)
        n = self.count(item_id) if num is None else num
        return {'itemId': item_id, 'itemTag': tag, 'baseItem': {'itemId': item_id, 'num': str(n)}}

    def add_items(self, pairs):
        """Grant [(item_id, n)]. Returns (rsp_items, changed_infos) as ItemDetail lists."""
        got, changed = [], []
        for iid, n in pairs:
            g, c = self.add_item(iid, n)
            got += g; changed += c
        if pairs and not self.__dict__.get('_in_quest_items'):
            from game import quests
            self._in_quest_items = True
            try:
                quests.on_items(self, pairs)
            finally:
                self._in_quest_items = False
        return got, changed

    def add_item(self, item_id, n=1):
        d = self.d
        tag = d.item_tag(item_id)
        got, changed = [], []
        if tag == 'EBagItemTag_Card' or d.row('character', 'Character', item_id) and tag in ('EBagItemTag_Card', 'EBagItemTag_None'):
            for _ in range(n):
                if str(item_id) in self.s['characters']:
                    rep = (d.row('character', 'Character', item_id) or {}).get('RepeatItemID')
                    info = {'itemId': item_id, 'itemTag': tag}
                    det = {'mainItem': info}
                    if rep:
                        self.s['items'][str(rep)] = self.count(rep) + 1
                        det['transformedItem'] = [{'itemId': rep, 'itemTag': d.item_tag(rep), 'baseItem': {'itemId': rep, 'num': '1'}}]
                        changed.append({'mainItem': self.item_info(rep)})
                    got.append(det)
                else:
                    ch = self.add_character(item_id)
                    got.append({'mainItem': {'itemId': item_id, 'itemTag': tag, 'character': ch}})
            return got, changed
        if tag in INSTANCE_TAGS:
            for _ in range(n):
                inst = self.new_instance(tag, item_id)
                info = self.instance_info(tag, inst)
                got.append({'mainItem': info}); changed.append({'mainItem': info})
            return got, changed
        if tag == 'EBagItemTag_Fashion':
            self.s['outfits'].setdefault(str(item_id), {'outfitId': item_id, 'dyeSchemes': [{'isUnLock': True}]})
        if tag == 'EBagItemTag_UnlockItem' and item_id not in self.s['unlock_functions']:
            self.s['unlock_functions'].append(item_id)
        if tag == 'EBagItemTag_PlayerExp':
            self.add_exp(n)
        self.s['items'][str(item_id)] = self.count(item_id) + n
        self.dirty = True
        got.append({'mainItem': self.item_info(item_id, n)})
        changed.append({'mainItem': self.item_full_info(item_id)})
        return got, changed

    def item_full_info(self, item_id):
        tag = self.d.item_tag(item_id)
        if tag == 'EBagItemTag_Fashion' and str(item_id) in self.s['outfits']:
            return {'itemId': item_id, 'itemTag': tag, 'outfit': self.s['outfits'][str(item_id)]}
        return self.item_info(item_id)

    def remove_item(self, item_id, n=1):
        have = self.count(item_id)
        if have < n:
            return None
        self.s['items'][str(item_id)] = have - n
        self.dirty = True
        return [{'mainItem': self.item_info(item_id)}]

    def can_afford(self, costs):
        return all(self.count(i) >= n for i, n in costs)

    def pay(self, costs):
        if not self.can_afford(costs):
            return None
        out = []
        for i, n in costs:
            out += self.remove_item(i, n)
        return out

    # ------------------------------------------------------------ instances
    def new_instance(self, tag, item_id):
        iid = self._next_iid()
        d = self.d
        if tag == 'EBagItemTag_Weapon':
            lvl = max(1, self.s.get('level', 1))
            inst = {'weaponId': item_id, 'instanceId': iid, 'level': lvl, 'star': 1, 'durability': 100, 'propertyIndex': 1}
            g = self.weapon_group(item_id, lvl)
            if g:
                inst['attack'] = int(random.uniform(g.get('MinAttack', 20), g.get('MaxAttack', g.get('MinAttack', 20))))
                inst['criticalRatio'] = int(g.get('MinCriticalRatio', 0.02) * 1000)
                inst['damageBalance'] = int(g.get('MinDamageBalance', 1.0) * 30)
            inst.setdefault('attack', 20); inst.setdefault('criticalRatio', 20); inst.setdefault('damageBalance', 30)
        elif tag == 'EBagItemTag_Armor':
            inst = {'armorId': item_id, 'instanceId': iid, 'level': 1, 'propertyIndex': 1,
                    'mainPropertyType': 'EPropertyType_ExtHp', 'mainPropertyVal': 50}
        elif tag == 'EBagItemTag_Poster':
            inst = {'posterId': item_id, 'instanceId': iid, 'star': 1}
        elif tag == 'EBagItemTag_Pet':
            inst = {'itemId': item_id, 'instance_id': iid, 'level': 1, 'catch_time': str(int(time.time()))}
        else:
            inst = {'instanceId': iid}
        self.s[INSTANCE_TAGS[tag]][str(iid)] = inst
        self.dirty = True
        return inst

    def weapon_group(self, weapon_id, level):
        w = self.d.row('weapon', 'Weapon', weapon_id) or {}
        prop = self.d.row('weapon', 'WeaponProperty', w.get('WeaponPropertyID')) or {}
        gs = prop.get('WeaponPropertyGroupInfo', [])
        for g in gs:
            if g.get('MinLevel', 1) <= level <= g.get('MaxLevel', 999):
                return g
        return gs[-1] if gs else None

    @staticmethod
    def instance_info(tag, inst):
        key = {'EBagItemTag_Weapon': 'weapon', 'EBagItemTag_Armor': 'armor', 'EBagItemTag_Poster': 'poster',
               'EBagItemTag_Pet': 'pet'}[tag]
        iid = inst.get('instanceId') or inst.get('instance_id')
        return {'itemId': iid, 'itemTag': tag, key: inst}

    # ------------------------------------------------------------ characters
    def add_character(self, cid):
        d = self.d
        c = d.row('character', 'Character', cid) or {}
        ch = {'characterId': cid, 'level': 1, 'maxLevel': 20, 'star': 1,
              'equipmentPresets': [{'presetIndex': i} for i in range(3)],
              'outfitPresets': [{'presetIndex': i, 'hair': c.get('HairID', 0), 'clothes': c.get('ClothID', 0), 'outfitHideInfo': {}}
                                for i in range(3)],
              'characterAppearance': {}, 'characterSkillList': []}
        for f in (c.get('HairID'), c.get('ClothID')):
            if f:
                self.s['outfits'].setdefault(str(f), {'outfitId': f, 'dyeSchemes': [{'isUnLock': True}]})
                self.s['items'][str(f)] = max(1, self.count(f))
        if c.get('DefaultWeaponID'):
            w = self.new_instance('EBagItemTag_Weapon', c['DefaultWeaponID'])
            w['wearerId'] = cid
            ch['equipmentPresets'][0]['weapon'] = w['instanceId']
        self.s['characters'][str(cid)] = ch
        self.dirty = True
        return ch

    def add_exp(self, n):
        self.s['exp'] += n
        while True:
            row = self.d.row('level', 'PlayerLevel', self.s['level'])
            if not row or self.s['exp'] < row.get('NeedExp', 10 ** 9) or not self.d.row('level', 'PlayerLevel', self.s['level'] + 1):
                break
            self.s['exp'] -= row['NeedExp']; self.s['level'] += 1
            self.__dict__['_leveled'] = True

    # ------------------------------------------------------------ views
    def pack_items(self):
        out = []
        for k, n in self.s['items'].items():
            iid = int(k)
            if n <= 0 and self.d.item_tag(iid) != 'EBagItemTag_Fashion':
                continue
            out.append({'mainItem': self.item_full_info(iid)})
        for tag, key in INSTANCE_TAGS.items():
            for inst in self.s[key].values():
                out.append({'mainItem': self.instance_info(tag, inst)})
        return out

    def main_data(self):
        from game import quests
        s = self.s
        return {
            'status': 'StatusCode_OK', 'player_id': s['player_id'], 'player_name': s['name'],
            'is_today_first_login': time.strftime('%Y%m%d', time.localtime(s.get('last_login', 0))) != time.strftime('%Y%m%d'),
            'unlockFunctions': s['unlock_functions'], 'level': s['level'], 'exp': s['exp'], 'head': s['head'],
            'sign': s['sign'], 'phone_background': s['phone_background'], 'world_level': s['world_level'],
            'create_time': s['create_time'], 'characters': list(s['characters'].values()), 'team': s['team'],
            'scene_id': s['scene_id'], 'channel_id': s['channel_id'] or s['player_id'],
            'quest_detail': quests.quest_detail(self),
            'player_label': s['player_label'], 'channel_label': s['player_label'],
            'gardenLikesNum': s['garden']['likes'],
            'furnitureItemInfo': [{'itemId': int(k), 'num': str(v)} for k, v in self.furniture_used().items() if v > 0],
            'birthday': s['birthday'], 'accountType': 16666, 'appearance': s.get('appearance', {}),
            'placed_characters': s['placed_characters'], 'phone_case': s['phone_case'],
            'sex': s.get('sex') or 0, 'isHideBirthday': s.get('hide_birthday', False),
            'pet_instance_id': s.get('pet_instance_id', 0), 'reward_levels': s.get('level_rewards', []),
            'playerDropRateInfo': {'killDropRate': 100, 'treasureDropRate': 100},
            # sub-messages official always sends (null on the client if absent; its login setup stops on them)
            'daily_task': self._daily_task(), 'questionnaire_info': {},
            'player_buffs': self._player_buffs(),
        }
