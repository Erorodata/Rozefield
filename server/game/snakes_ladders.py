"""Co-op Snakes & Ladders in Rota Plaza using the in-game Special Dice (item 2020).

Players start or join a match in their current plaza channel with chat commands:
  /sl start   - open a new Snakes & Ladders room in your channel (and join it)
  /sl join    - join the open room in your channel
  /sl status  - show player tile positions and whose turn it is
  /sl board   - show all Ladders and Snakes on the 30-tile board
  /sl leave   - leave the current match

Movement is driven by throwing the in-game Special Dice (item 2020): ThrowDiceReq
reports the exact rolled face value (pips, 1..6), which advances the player's tile
by that exact number, applies any Ladder boost or Snake slide, and broadcasts the
result to everyone in the plaza channel.

Rewards on match finish (reaching tile 30):
  - Winner:            10,000 Feline Tokens (item 109)
  - Other participants: 5,000 Feline Tokens (item 109)
"""
import time

OK = 'StatusCode_OK'
DICE_ITEM = 2020
DICE_TOPUP = 10
REWARD_ITEM = 109       # Feline Token
REWARD_WINNER = 10000
REWARD_PARTICIPANT = 5000

GOAL_TILE = 30
LADDERS = {3: 11, 6: 15, 10: 19, 14: 23, 20: 27}
SNAKES = {13: 5, 18: 9, 24: 16, 28: 12, 29: 21}

# Active rooms keyed by (scene_id, channel_id)
_ROOMS = {}
# Reverse lookup: player_id -> (scene_id, channel_id)
_PLAYER_ROOM = {}


def _now_ms():
    return str(int(time.time() * 1000))


def _room_key(p):
    return (p.s.get('scene_id', 9999), p.s.get('channel_id', 1))


def _announce(ctx, text, room=None, self_only=False):
    """Send a system-style ChatMsgNotice to the player or everyone in the plaza channel."""
    msg = {
        'playerId': 0,
        'head': 41101,
        'name': 'Snakes & Ladders',
        'text': text,
        'expression': 0,
        'sendTime': _now_ms(),
        'avatarFrame': 0,
    }
    note = {'status': OK, 'type': 'ChatChannel_Default', 'msg': msg}
    if self_only:
        try:
            ctx.push('ChatMsgNotice', note)
        except Exception:
            pass
        return
    # Broadcast to everyone in the same scene/channel (including sender)
    ctx.server.broadcast(ctx, 'ChatMsgNotice', note, include_self=True)


def _topup_dice(ctx, pack, target=DICE_TOPUP):
    p = ctx.p
    have = p.count(DICE_ITEM)
    if have < target:
        _, changed = p.add_item(DICE_ITEM, target - have)
        if changed:
            pack(ctx, changed)
        p.dirty = True


def _board_summary():
    lads = ', '.join(f'{a}->{b}' for a, b in sorted(LADDERS.items()))
    snks = ', '.join(f'{a}->{b}' for a, b in sorted(SNAKES.items()))
    return f'Board 1..{GOAL_TILE} | Ladders: {lads} | Snakes: {snks}'


def _status_text(room):
    order = room['order']
    turn_pid = order[room['turn'] % len(order)]
    parts = []
    for pid in order:
        marker = '*' if pid == turn_pid else ''
        parts.append(f"{marker}{room['names'].get(pid, pid)}:{room['pos'].get(pid, 1)}/{GOAL_TILE}")
    return 'Positions: ' + ' | '.join(parts) + f" (Turn: {room['names'].get(turn_pid, turn_pid)})"


def is_in_match(pid):
    return pid in _PLAYER_ROOM


def handle_command(ctx, text, pack):
    """Handle /sl chat commands. Returns True if handled (so normal chat is still clean)."""
    parts = text.strip().split()
    if not parts or parts[0].lower() != '/sl':
        return False
    sub = parts[1].lower() if len(parts) > 1 else 'help'
    p = ctx.p
    pid = p.s['player_id']
    pname = p.s.get('name') or str(pid)
    key = _room_key(p)

    if sub in ('help', '?'):
        _announce(ctx,
                  f'Commands: /sl start, /sl join, /sl status, /sl board, /sl leave. '
                  f'Throw Special Dice to move! Rewards: {REWARD_WINNER:,} Feline Tokens (winner) / {REWARD_PARTICIPANT:,} (participant).',
                  self_only=True)
        return True

    if sub == 'board':
        _announce(ctx, _board_summary(), self_only=True)
        return True

    if sub == 'start':
        if pid in _PLAYER_ROOM:
            _announce(ctx, 'You are already in a Snakes & Ladders match. Use /sl leave first.', self_only=True)
            return True
        if key in _ROOMS:
            _announce(ctx, 'A Snakes & Ladders match is already open here! Type /sl join to join it.', self_only=True)
            return True
        room = {
            'key': key,
            'order': [pid],
            'names': {pid: pname},
            'pos': {pid: 1},
            'turn': 0,
            'started': False,
        }
        _ROOMS[key] = room
        _PLAYER_ROOM[pid] = key
        _topup_dice(ctx, pack)
        _announce(ctx,
                  f'{pname} started Snakes & Ladders (1..{GOAL_TILE})! Type /sl join to play, or throw your Special Dice to roll first!')
        return True

    if sub == 'join':
        if pid in _PLAYER_ROOM:
            _announce(ctx, 'You are already in a Snakes & Ladders match.', self_only=True)
            return True
        room = _ROOMS.get(key)
        if not room:
            _announce(ctx, 'No Snakes & Ladders match here yet. Type /sl start to create one!', self_only=True)
            return True
        if pid not in room['order']:
            room['order'].append(pid)
            room['names'][pid] = pname
            room['pos'][pid] = 1
        _PLAYER_ROOM[pid] = key
        _topup_dice(ctx, pack)
        _announce(ctx, f'{pname} joined Snakes & Ladders! ({len(room["order"])} players) {_status_text(room)}')
        return True

    if sub == 'status':
        room = _ROOMS.get(_PLAYER_ROOM.get(pid) or key)
        if not room:
            _announce(ctx, 'No active Snakes & Ladders match here. Type /sl start to begin!', self_only=True)
            return True
        _announce(ctx, _status_text(room), self_only=True)
        return True

    if sub == 'leave':
        rkey = _PLAYER_ROOM.pop(pid, None)
        room = _ROOMS.get(rkey) if rkey else None
        if not room:
            _announce(ctx, 'You are not in a Snakes & Ladders match.', self_only=True)
            return True
        if pid in room['order']:
            idx = room['order'].index(pid)
            room['order'].remove(pid)
            if room['order']:
                if idx < room['turn']:
                    room['turn'] -= 1
                room['turn'] %= len(room['order'])
        if not room['order']:
            _ROOMS.pop(rkey, None)
            _announce(ctx, f'{pname} left. Snakes & Ladders match ended.')
        else:
            _announce(ctx, f'{pname} left Snakes & Ladders. {_status_text(room)}')
        return True

    _announce(ctx, 'Unknown /sl command. Try: /sl start, /sl join, /sl status, /sl board, /sl leave.', self_only=True)
    return True


def on_dice_throw(ctx, pips, pack):
    """Called from ThrowDiceReq when a player throws Special Dice with a valid pip value (1..6).

    Returns True if the player is in an active Snakes & Ladders match (so the dice is refunded).
    """
    p = ctx.p
    pid = p.s['player_id']
    rkey = _PLAYER_ROOM.get(pid)
    if not rkey:
        return False
    room = _ROOMS.get(rkey)
    if not room or pid not in room['order']:
        _PLAYER_ROOM.pop(pid, None)
        return False

    order = room['order']
    turn_pid = order[room['turn'] % len(order)]
    pname = room['names'].get(pid, p.s.get('name') or str(pid))

    if pid != turn_pid:
        turn_name = room['names'].get(turn_pid, str(turn_pid))
        _announce(ctx, f"Hold on {pname}! It's {turn_name}'s turn to throw the Special Dice.", self_only=True)
        return True

    room['started'] = True
    roll = max(1, min(6, int(pips)))
    old_pos = room['pos'].get(pid, 1)
    new_pos = min(GOAL_TILE, old_pos + roll)
    note = ''
    if new_pos in LADDERS:
        dest = LADDERS[new_pos]
        note = f' -> LADDER! Climbed {new_pos} to {dest}!'
        new_pos = dest
    elif new_pos in SNAKES:
        dest = SNAKES[new_pos]
        note = f' -> SNAKE! Slid {new_pos} down to {dest}!'
        new_pos = dest
    room['pos'][pid] = new_pos

    if new_pos >= GOAL_TILE:
        # Match finished — award Feline Tokens to winner & all participants
        _ROOMS.pop(rkey, None)
        for mpid in list(order):
            _PLAYER_ROOM.pop(mpid, None)
            amount = REWARD_WINNER if mpid == pid else REWARD_PARTICIPANT
            sess = ctx.server.sessions.get(mpid)
            if sess and sess.p:
                _, ch = sess.p.add_item(REWARD_ITEM, amount)
                if ch:
                    pack(sess, ch)
                sess.p.save()
        _announce(ctx,
                  f'{pname} rolled {roll} ({old_pos} -> {new_pos}){note} and WON Snakes & Ladders! '
                  f'Rewards sent: {REWARD_WINNER:,} Feline Tokens to {pname}, {REWARD_PARTICIPANT:,} to each participant!')
        return True

    # Advance turn
    room['turn'] = (room['turn'] + 1) % len(order)
    nxt_pid = order[room['turn']]
    nxt_name = room['names'].get(nxt_pid, str(nxt_pid))
    _announce(ctx, f'{pname} rolled {roll}: tile {old_pos} -> {new_pos}/{GOAL_TILE}{note} | Next turn: {nxt_name}')
    return True


def on_disconnect(pid):
    """Clean up if a player disconnects mid-match."""
    rkey = _PLAYER_ROOM.pop(pid, None)
    if not rkey:
        return
    room = _ROOMS.get(rkey)
    if not room:
        return
    if pid in room['order']:
        idx = room['order'].index(pid)
        room['order'].remove(pid)
        if room['order']:
            if idx < room['turn']:
                room['turn'] -= 1
            room['turn'] %= len(room['order'])
    if not room['order']:
        _ROOMS.pop(rkey, None)
