"""Generic optional DLC module loader for Rozefield.

Core Rozefield stays 100% free of expansion code. Any optional DLC pack placed in
`<server_dir>/dlc/<pack_id>/` with `manifest.json` (`{"enabled": true}`) and `dlc.py`
is discovered and loaded at server startup. Removing or disabling the folder leaves
base Rozefield completely untouched.
"""
import importlib.util
import json
import logging
import os

log = logging.getLogger('rozefield')

LOADED = {}          # pack_id -> {'manifest': dict, 'module': module}
_CHAT_HOOKS = []     # list of fn(ctx, text, pack) -> bool
_EXP_HOOKS = []      # list of fn(player) -> bool


def load_all(server_dir, H, pack, scene_player):
    """Discover and register all enabled DLC packs under <server_dir>/dlc/."""
    dlc_root = os.path.join(server_dir, 'dlc')
    if not os.path.isdir(dlc_root):
        return
    api = {
        'H': H,
        'pack': pack,
        'scene_player': scene_player,
        'add_chat_hook': _CHAT_HOOKS.append,
        'add_exp_hook': _EXP_HOOKS.append,
    }
    for name in sorted(os.listdir(dlc_root)):
        folder = os.path.join(dlc_root, name)
        mpath = os.path.join(folder, 'manifest.json')
        entry = os.path.join(folder, 'dlc.py')
        if not (os.path.isdir(folder) and os.path.isfile(mpath) and os.path.isfile(entry)):
            continue
        try:
            manifest = json.load(open(mpath, encoding='utf-8'))
            if not manifest.get('enabled', True):
                continue
            pid = manifest.get('id') or name
            spec = importlib.util.spec_from_file_location(f'rozefield_dlc_{pid}', entry)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, 'register'):
                mod.register(api)
            LOADED[pid] = {'manifest': manifest, 'module': mod}
            log.info('DLC loaded: %s v%s (%s)', manifest.get('name', pid), manifest.get('version', '1.0'), pid)
        except Exception:
            log.exception('Failed to load DLC pack %s', name)


def dispatch_chat(ctx, text, pack):
    """Give loaded DLCs first chance to handle a chat command (returns True if consumed)."""
    for fn in _CHAT_HOOKS:
        try:
            if fn(ctx, text, pack):
                return True
        except Exception:
            log.exception('DLC chat hook error')
    return False


def run_exp_hooks(player):
    """Allow loaded DLCs to handle post-cap EXP/leveling (e.g. opt-in breakthrough)."""
    for fn in _EXP_HOOKS:
        try:
            fn(player)
        except Exception:
            log.exception('DLC exp hook error')
