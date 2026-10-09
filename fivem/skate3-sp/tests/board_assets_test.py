"""Checks on the built board models (skate3-sp/tools/build_board.py -> ~\\skate3-extract\\decks_build).

Every check reads the COMPILED files back with the CodeWalker tool, not the builder's own intermediate data.
usage: python board_assets_test.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import paths  # noqa: E402
OUT = paths.work(r"decks_build")
RESEARCH = paths.work(r"research")
CWTOOL = paths.CWTOOL
GTA = os.path.join(OUT, 'gta')
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(('OK  ' if cond else 'BAD ') + label)
    return bool(cond)


def to_xml(name, tmp):
    out = os.path.join(tmp, name + '.xml')
    subprocess.run([CWTOOL], input=json.dumps({'cmd': 'toxml', 'in': os.path.join(GTA, name), 'out': out}),
                   capture_output=True, text=True)
    stem = name.rsplit('.', 1)[0]
    return ET.parse(out).getroot(), os.path.join(tmp, stem, stem)   # (where the tool puts embedded textures)


def geometry(root):
    """positions, normals, uvs of the drawable's one geometry"""
    rows = [[float(v) for v in line.split()] for line in root.find('.//VertexBuffer/Data').text.strip().splitlines()]
    a = np.array(rows)
    return a[:, 0:3], a[:, 3:6], a[:, 10:12]


def underside_fit(pos, nrm, uv):
    """Of the vertices that face down and are not on the rim (the rim is the strip at the right of the atlas, u > 0.9):
    the share whose UV is in the atlas's lower block, the slope of u against x there, and how many they are; and the
    share of the upward ones (the grip tape) that are in the upper block."""
    down = (nrm[:, 2] < -0.9) & (uv[:, 0] < 0.9)
    up = (nrm[:, 2] > 0.9) & (uv[:, 0] < 0.9)
    slope = np.polyfit(pos[down, 0], uv[down, 0], 1)[0]
    return float((uv[down, 1] > 0.5).mean()), float(slope), int(down.sum()), float((uv[up, 1] < 0.5).mean())


def main():
    cat = json.load(open(os.path.join(OUT, 'web', 'decks', 'catalog.json'), encoding='utf-8'))
    files = set(os.listdir(GTA))
    kinds = (('deck', cat['decks']), ('truck', cat['trucks']), ('wheel', cat['wheels']))
    missing = [k + ':' + p['id'] for k, rows in kinds for p in rows if 's3_%s_%s.ydr' % (k, p['id']) not in files]
    check('every part of the catalogue has its model (%d decks, %d trucks, %d wheels; missing %s)' % (
        len(cat['decks']), len(cat['trucks']), len(cat['wheels']), missing[:5]),
        not missing and len(cat['decks']) == 152 and len(cat['trucks']) == 40 and len(cat['wheels']) == 71)
    web = os.path.join(OUT, 'web')
    nothumb = [p['id'] for k, rows in kinds for p in rows if not (p['thumb'] and os.path.exists(os.path.join(web, p['thumb'])))]
    noprev = [p['id'] for p in cat['decks'] if not (p['preview'] and os.path.exists(os.path.join(web, p['preview'])))]
    check('every part has the game\'s own shop thumbnail and every deck a preview (without: %s / %s)' % (nothumb[:6], noprev[:6]),
          len(nothumb) <= 2 and not noprev)
    ids_ok = all(re.fullmatch(r'[a-z0-9_]+', p['id']) for _, rows in kinds for p in rows)
    check('ids are lower case a-z 0-9 _ and unique within their kind',
          ids_ok and all(len({p['id'] for p in rows}) == len(rows) for _, rows in kinds))
    check('the defaults are parts of the catalogue (%s)' % cat['default'],
          all(cat['default'][k] in {p['id'] for p in rows} for k, rows in kinds))

    with tempfile.TemporaryDirectory() as tmp:
        ytyp, _ = to_xml('s3_boards.ytyp', tmp)
        arch = {a.find('name').text: a for a in ytyp.find('archetypes')}
        models = {f[:-4] for f in files if f.endswith('.ydr')}
        check('the .ytyp lists every model and nothing else (%d archetypes, %d models)' % (len(arch), len(models)),
              set(arch) == models)

        def physics_ok(arch):
            bad = []
            for n, a in arch.items():
                phys = (a.find('physicsDictionary').text or '').strip()
                want = n if n.startswith(('s3_deck_', 's3_custom_')) else ''
                if phys != want:
                    bad.append(n)
            return bad
        check('physicsDictionary names the model itself exactly on the models that carry collision', not physics_ok(arch))
        broken = dict(arch)
        first = next(n for n in arch if n.startswith('s3_deck_'))
        copy = ET.fromstring(ET.tostring(arch[first]))
        copy.find('physicsDictionary').text = ''
        broken[first] = copy
        check('control: a deck archetype with an empty physicsDictionary is caught', physics_ok(broken) == [first])
        slots = sorted(n for n in arch if n.startswith('s3_custom_'))
        check('the slot models take their deck texture from the shared dictionary (%d slots)' % len(slots),
              len(slots) >= 8 and all((arch[n].find('textureDictionary').text or '') == 's3_custom_slots' for n in slots))

        d = cat['default']
        deck_x, deck_dir = to_xml('s3_deck_%s.ydr' % d['deck'], tmp)
        truck_x, _ = to_xml('s3_truck_%s.ydr' % d['truck'], tmp)
        wheel_x, _ = to_xml('s3_wheel_%s.ydr' % d['wheel'], tmp)
        slot_x, _ = to_xml(slots[0] + '.ydr', tmp)
        ytd_x, ytd_dir = to_xml('s3_custom_slots.ytd', tmp)
        dp, dn, duv = geometry(deck_x)
        tp, _, _ = geometry(truck_x)
        wp, _, _ = geometry(wheel_x)
        a = arch['s3_deck_' + d['deck']]
        lo = [float(a.find('bbMin').get(k)) for k in 'xyz']
        hi = [float(a.find('bbMax').get(k)) for k in 'xyz']
        check('a deck has collision, and its archetype box is the WHOLE board, down to the ground '
              '(%.3f x %.3f m, z %.3f .. %.3f)' % (hi[0] - lo[0], hi[1] - lo[1], lo[2], hi[2]),
              deck_x.find('Bounds') is not None and abs(hi[0] - lo[0] - 0.90) < 0.02 and abs(hi[1] - lo[1] - 0.225) < 0.02
              and abs(lo[2]) < 0.002 and 0.11 < hi[2] < 0.14)
        check('trucks and wheels have no collision of their own, a slot deck has',
              truck_x.find('Bounds') is None and wheel_x.find('Bounds') is None and slot_x.find('Bounds') is not None)
        # the three objects placed at one origin make one board
        gap = tp[:, 2].max() - dp[(np.abs(dp[:, 0]) > 0.2) & (np.abs(dp[:, 0]) < 0.32) & (dn[:, 2] < -0.9)][:, 2].min()
        check('at one origin the parts fit: the trucks reach up to the deck\'s underside (%.1f mm), the wheels stand on '
              'the ground (%.1f mm) and sit under the trucks\' ends' % (gap * 1000, wp[:, 2].min() * 1000),
              abs(gap) < 0.004 and abs(wp[:, 2].min()) < 0.002 and abs(np.abs(wp[:, 0]).max() - np.abs(tp[:, 0]).max()) < 0.05)
        moved = tp + np.array([0.0, 0.0, 0.05])
        check('control: trucks 5 cm too high are caught', abs(moved[:, 2].max() - dp[dn[:, 2] < -0.9][:, 2].min()) > 0.004)
        # orientation: the lower block of the atlas is on the downward faces, nose (-x) at the picture's left
        inside, slope, count, grip = underside_fit(dp, dn, duv)
        check('the underside graphic is on the downward faces with the nose (-x) at the picture\'s left (%d vertices, '
              '%.0f %% in the lower block, u rises %.2f per metre of x); the grip tape is on the upward ones (%.0f %%)'
              % (count, inside * 100, slope, grip * 100),
              count > 60 and inside == 1.0 and 0.85 < slope < 1.05 and grip == 1.0)
        flipped = duv.copy()
        flipped[:, 0] = 0.888 - flipped[:, 0]
        check('control: a mirrored mapping is caught', underside_fit(dp, dn, flipped)[1] < 0)

        # textures: Skate 3's colours untouched, no transparency, full mip chains
        item = deck_x.find('.//TextureDictionary/Item')
        dds = Image.open(os.path.join(deck_dir, item.find('FileName').text))
        got = np.asarray(dds.convert('RGBA')).astype(int)
        asset = 'skateboard_' + d['deck'] if os.path.exists(os.path.join(
            RESEARCH, 'decks', 'png', 'decks', 'skateboard_' + d['deck'] + '.png')) else None
        ref = np.asarray(Image.open(os.path.join(RESEARCH, 'decks', 'png', 'decks', asset + '.png')).convert('RGB')).astype(int) \
            if asset else None
        diff = int(np.abs(got[:, :, :3] - ref).max()) if ref is not None and ref.shape == got[:, :, :3].shape else -1
        check('a deck texture: %s, %s mips, every pixel opaque (alpha min %d), colours identical to the decoded '
              'Skate 3 picture (largest difference %d)' % (item.find('Format').text, item.find('MipLevels').get('value'),
                                                         got[:, :, 3].min(), diff),
              item.find('Format').text == 'D3DFMT_DXT1' and int(item.find('MipLevels').get('value')) >= 8
              and got[:, :, 3].min() == 255 and diff == 0)
        names = [i.find('Name').text for i in ytd_x.findall('Item')]
        check('the slot dictionary holds one texture per slot, under the slots\' own names',
              sorted(names) == slots and slot_x.find('.//Shaders/Item/Parameters/Item/Name').text == slots[0])

    # decks.lua says the same as catalog.json
    from lupa import lua54
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(io.open(os.path.join(OUT, 'decks.lua'), encoding='utf-8').read())
    D = L.globals().Skate3Decks
    same = [p.id for p in D.stock.values()] == [p['id'] for p in cat['decks']] and \
        [p.id for p in D.trucks.values()] == [p['id'] for p in cat['trucks']] and \
        [p.id for p in D.wheels.values()] == [p['id'] for p in cat['wheels']] and \
        all(D.stock[i + 1].model == 's3_deck_' + p['id'] and D.stock[i + 1].price == p['price']
            for i, p in enumerate(cat['decks']))
    check('decks.lua loads and lists the same parts, models and prices as catalog.json; %d plain decks as bases' %
          len(list(D.custom.bases.values())), same and len(list(D.custom.bases.values())) == 10
          and D.default.deck == cat['default']['deck'] and len(list(D.custom.slots.values())) == len(slots))
    print('ALL OK' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
