"""Copy the captured player's event progress (pass, gashapon, wishing tree, sign-in, abyss, friendship points)
from a decoded official capture into a Rozefield save.

    py tools/import_events.py capture_decoded.json save/accounts/<pid>.json
"""
import json
import sys


def main(dec, save):
    d = json.load(open(dec, encoding='utf-8'))
    s = json.load(open(save, encoding='utf-8'))
    ev = s.setdefault('events', {})
    for p in d:
        n, b = p.get('name'), p.get('body') or {}
        if n == 'ActivityBattlePassInfoNotice':
            for i in b.get('info', []):
                ev.setdefault('battlepass', {})[str(i['activityId'])] = {
                    'totalExp': int(i.get('totalExp', 0)), 'weekExp': i.get('weekExp', 0), 'week': '', 'day': '',
                    'free': i.get('freeLvRewardLst', []), 'daily': [], 'weekly': [], 'season': i.get('seasonAchieveRewardLst', [])}
        elif n == 'ActivityTurntableDataNotice':
            for a in b.get('activities', []):
                drawn = {}
                for k, it in a.get('items', {}).items():
                    if 'remainCount' in it:
                        drawn[k] = None   # filled below from the table limit
                    drawn[k] = it.get('remainCount')
                ev.setdefault('turntable', {})[str(a['activityId'])] = {'remain': drawn, 'drawn': {}, 'draws': 1}
        elif n == 'BlessTreeNotice':
            ev['bless'] = {k: v.get('treeIds', []) for k, v in b.get('tress', {}).items()}
        elif n == 'ActivitySignInDataNotice':
            for i in b.get('info', []):
                ev.setdefault('signin', {})[str(i['activityId'])] = {'mask': i.get('rewardId', 0), 'days': i.get('loginDay', 0),
                                                                     'day': '', 'first': int(i.get('initTime', 0) or 0)}
        elif n == 'AbyssInfoRsp':
            for sid, v in (b.get('abyssInfo') or {}).get('seasonInfo', {}).items():
                ev.setdefault('abyss', {})[sid] = v.get('dungeonInfo', {})
        elif n == 'FriendRsp':
            for f in b.get('info', []):
                if f.get('friend_intimacy'):
                    ev.setdefault('intimacy', {})[str(f['info']['playerId'])] = f['friend_intimacy']
        elif n == 'UseItemFriendIntimacyRsp':
            ev.setdefault('intimacy', {})[str(b['friend_id'])] = b['intimacy']
        elif n == 'BlessTreeUnlockRsp':
            ev.setdefault('bless', {}).setdefault(str(b['defId']), [])
            if b['treeId'] not in ev['bless'][str(b['defId'])]:
                ev['bless'][str(b['defId'])].append(b['treeId'])
        elif n == 'ActivityBattlePassBuyExpRsp':
            bp = ev.get('battlepass', {}).get(str(b['activityBattlePassId']))
            if bp:
                bp['totalExp'] = int(b['totalExp'])
        elif n == 'GetActivityBattlePassLevelRewardRsp':
            for bp in ev.get('battlepass', {}).values():
                lv = 0
                for p2 in d:
                    if p2.get('name') == 'ActivityBattlePassBuyExpRsp':
                        lv = max(lv, p2['body'].get('battlePassLv', 0))
                bp['free'] = sorted(set(bp['free']) | set(range(1, lv + 1)))
        elif n == 'GetActivityBattlePassQuestRewardRsp':
            for bp in ev.get('battlepass', {}).values():
                bp['totalExp'], bp['weekExp'] = int(b['currentTotalExp']), b['currentWeekExp']
    json.dump(s, open(save, 'w', encoding='utf-8'), ensure_ascii=False)
    print('events imported:', {k: len(v) for k, v in ev.items() if isinstance(v, dict)})


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
