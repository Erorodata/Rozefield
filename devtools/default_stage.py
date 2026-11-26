"""Rozefield: the plaza always shows the default stage (no seasonal event decoration).

The client picks the plaza stage itself (SceneHomeController.InitSceneTheme): it skips SceneTheme ID 1 (default),
and uses the last row whose OpeningTime..ClosingTime holds the current date; rows without dates are skipped.
Clearing the dates of every event row means none ever matches, so the default stage stays.

    py tools\\default_stage.py <pbstaticconfigure.bundle>          (patches the bundle in place)

merge_cn_config.py applies the same change (clear_event_themes) when it rebuilds the bundle.
"""
import os, sys
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # devtools package


def clear_event_themes(g):
    """g = scene table as JSON. Returns how many event rows were switched off."""
    n = 0
    for r in g.get('SceneTheme', {}).get('datas', []):
        if r.get('ID') != 1 and (r.get('OpeningTime') or r.get('ClosingTime')):
            r.pop('OpeningTime', None)
            r.pop('ClosingTime', None)
            n += 1
    return n


def main():
    path = sys.argv[1]
    import UnityPy
    from google.protobuf import json_format, message_factory
    from ofproto import pool
    name = 'protocol.AllSceneDatas'
    env = UnityPy.load(path)
    for p, obj in env.container.items():
        if os.path.basename(p) != 'scene.bytes':
            continue
        t = obj.read()
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(name))
        m = cls()
        m.ParseFromString(t.m_Script.encode('utf-8', 'surrogateescape'))
        g = json_format.MessageToDict(m, preserving_proto_field_name=True)
        n = clear_event_themes(g)
        m2 = cls()
        json_format.ParseDict(g, m2, ignore_unknown_fields=True)
        t.m_Script = m2.SerializeToString().decode('utf-8', 'surrogateescape')
        t.save()
        open(path, 'wb').write(env.file.save(packer='lz4'))
        print(f'scene: {n} event stage rows switched off -> {path}')
        return
    sys.exit('scene.bytes not found')


if __name__ == '__main__':
    main()
