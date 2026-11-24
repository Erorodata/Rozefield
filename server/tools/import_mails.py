"""Copy the captured player's mailbox from a decoded official capture into a Rozefield save. Mails titled
'OverField Farewell Rewards' (and any id given with --keep) are kept forever as mementos: they never expire
and 'Delete Read' leaves them alone.

    py tools/import_mails.py capture_decoded.json save/accounts/<pid>.json [--keep 1233]
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('decoded')
    ap.add_argument('save')
    ap.add_argument('--keep', type=int, nargs='*', default=[])
    a = ap.parse_args()
    d = json.load(open(a.decoded, encoding='utf-8'))
    s = json.load(open(a.save, encoding='utf-8'))
    box = {}
    for p in d:
        n, b = p.get('name'), p.get('body') or {}
        if n == 'GetMailsRsp':
            box = {m['mail_id']: m for m in b.get('mails', [])}
        elif n in ('OperateMailsRsp',) and box:
            for m in b.get('mails', []):
                box.setdefault(m['mail_id'], {}).update(m)
            for mid in b.get('deleted_mail_ids', []):
                box.pop(mid, None)
        elif n == 'ReceiveMailNotice' and b.get('mail') and box:
            box[b['mail']['mail_id']] = b['mail']
    keep = set(a.keep)
    for m in box.values():
        if 'Farewell' in (m.get('title') or ''):
            keep.add(m['mail_id'])
    for mid in keep:
        if mid in box:
            box[mid]['overdueDay'] = 9999
    old = {m['mail_id']: m for m in s.get('mails', [])}
    old.update(box)
    s['mails'] = sorted(old.values(), key=lambda m: int(m.get('send_time', 0) or 0), reverse=True)
    s['mail_keep'] = sorted(set(s.get('mail_keep', [])) | keep)
    json.dump(s, open(a.save, 'w', encoding='utf-8'), ensure_ascii=False)
    print('mails', len(s['mails']), 'kept forever', s['mail_keep'])


if __name__ == '__main__':
    main()
