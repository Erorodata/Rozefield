"""Rozefield feature: the plaza shows its default look, without the event decorations.

The official plaza scene (assets_scenes_home_scene.bundle) carries a group named "活动家具" (event furniture):
1,476 pieces from past events (Halloween trees, ghosts and pumpkins, the cake world, voxel buildings). It is part of
the scene itself, not server data, so it shows on every plaza channel. This tool switches that group off in a copy
of the bundle; the copy is then served in the Rozefield patch (the official game is not touched).

    py tools\\plaza_event_furniture.py <home scene bundle> <output bundle>

The patch is built from the Rozefield client's own manifest: replace the home scene bundle entry
(hash / crc / size, unity_crc 0) and give the manifest a new version, as for the config bundle.
"""
import sys

GROUP = '活动家具'


def main():
    src, dst = sys.argv[1], sys.argv[2]
    import UnityPy
    env = UnityPy.load(src)
    n = 0
    for o in env.objects:
        if o.type.name == 'GameObject':
            g = o.read()
            if g.m_Name == GROUP and g.m_IsActive:
                g.m_IsActive = False
                g.save()
                n += 1
    if not n:
        sys.exit(f'"{GROUP}" not found (or already off) in {src}')
    open(dst, 'wb').write(env.file.save(packer='lz4'))
    print(f'event furniture switched off -> {dst}')


if __name__ == '__main__':
    main()
