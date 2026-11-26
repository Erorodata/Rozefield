"""AssetBundle surgery for the CN->Global patch (needs UnityPy).

clone(): give a CN bundle a new bundle name and new internal CAB names so it can be loaded next to the
         Global bundle of the same original name (no "same files already loaded" conflict).
rewrite(): point a bundle's external references at cloned CABs.
"""
import hashlib


def cab_names(path):
    import UnityPy
    env = UnityPy.load(path)
    bf = list(env.files.values())[0]
    return [k for k in bf.files if k.startswith('CAB-')]


def new_cab(old, newname):
    tag = hashlib.md5((newname + '|' + old).encode()).hexdigest()
    return 'CAB-' + tag + old[36:]  # keep suffix such as .resS / .resource


def _swap(s, cab_map):
    for o, n in cab_map.items():
        s = s.replace(o, n)
    return s


def _walk(v, cab_map):
    if isinstance(v, str):
        return _swap(v, cab_map)
    if isinstance(v, list):
        return [_walk(x, cab_map) for x in v]
    if isinstance(v, dict):
        return {k: _walk(x, cab_map) for k, x in v.items()}
    return v


def process(src, out, cab_map, rename_to=None):
    """Load src bundle, rename its own CABs (cab_map keys it owns), rewrite externals, save to out."""
    import UnityPy
    env = UnityPy.load(src)
    bf = list(env.files.values())[0]
    olds = [k.encode() for k in cab_map]
    for key in list(bf.files):
        nk = _swap(key, cab_map)
        if nk != key:
            bf.files[nk] = bf.files.pop(key)
            if hasattr(bf.files[nk], 'name'):
                try:
                    bf.files[nk].name = nk
                except Exception:
                    pass
    for key, sf in bf.files.items():
        if not hasattr(sf, 'externals'):
            continue
        for e in sf.externals:
            e.path = _swap(e.path, cab_map)
        for obj in sf.objects.values():
            if rename_to and obj.type.name == 'AssetBundle':
                d = obj.read_typetree(); d['m_Name'] = rename_to; d['m_AssetBundleName'] = rename_to
                d = _walk(d, cab_map); obj.save_typetree(d)
                continue
            try:
                raw = obj.get_raw_data()
            except Exception:
                continue
            if any(o in raw for o in olds):  # streamed texture/mesh/audio data paths
                d = obj.read_typetree(); obj.save_typetree(_walk(d, cab_map))
    data = bf.save(packer='lz4')
    open(out, 'wb').write(data)
    return data
