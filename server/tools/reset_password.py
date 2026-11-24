"""Server owner tool: reset (or remove) a player's Rozefield password.

    python tools/reset_password.py <account or character name> <new password>
    python tools/reset_password.py <name> --clear      # next login sets a new password
    python tools/reset_password.py --list
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from rozefield_server import PW_FILE, _pw_load, set_password  # noqa: E402

ACC = os.path.join(HERE, 'save', 'accounts')


def accounts():
    reg_path = os.path.join(ACC, '_registry.json')
    reg = json.load(open(reg_path, encoding='utf-8')) if os.path.exists(reg_path) else {'by_uid': {}}
    for uid, pid in reg.get('by_uid', {}).items():
        nm = ''
        try:
            nm = json.load(open(os.path.join(ACC, f'{pid}.json'), encoding='utf-8')).get('name', '')
        except Exception:
            pass
        yield uid, nm
    for uid in _pw_load():
        if uid not in reg.get('by_uid', {}):
            yield uid, ''


def find(name):
    n = name.lower()
    for uid, nm in accounts():
        if uid.lower() in (n, 'rz_' + n) or nm.lower() == n:
            return uid
    return None


def main(a):
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return 1
    if a[0] == '--list':
        pw = _pw_load()
        for uid, nm in accounts():
            print(f"{uid:30} {nm:24} {'password set' if uid in pw else 'no password'}")
        return 0
    if len(a) < 2:
        print(__doc__); return 1
    uid = find(a[0])
    if not uid:
        print(f'No account called "{a[0]}". Use --list to see them.'); return 1
    if a[1] == '--clear':
        d = _pw_load(); d.pop(uid, None)
        json.dump(d, open(PW_FILE, 'w', encoding='utf-8'))
        print(f'{uid}: password removed. The next password used to log in becomes the new one.')
    else:
        if len(a[1]) < 4:
            print('Passwords need at least 4 characters.'); return 1
        set_password(uid, a[1])
        print(f'{uid}: password reset. Tell the player their new password.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
