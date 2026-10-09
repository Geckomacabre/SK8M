"""Build Skate 3's own skateboard for GTA V from your own Skate 3 dump (LOCAL ONLY, like everything in skate3_assets).

Skate 3 lets the player choose deck, trucks and wheels separately, so the board is three kinds of GTA model that share
one origin and one frame (long axis on x, nose at -x, origin on the ground under the middle of the deck: the convention
of GTA's own v_res_skateboard):

    s3_deck_<id>    the deck alone. This object is "the board": it carries the collision of the whole board, and its
                    archetype's box is the box of the whole board (the clip player measures the board with it).
    s3_truck_<id>   both trucks      } attached to the deck object with no offset; no collision of their own
    s3_wheel_<id>   all four wheels  }
    s3_custom_NN    the deck again, for a player's own picture: its texture is "s3_custom_NN" in the shared dictionary
                    s3_custom_slots.ytd, which a script replaces at run time (FiveM) or the installer bakes (single player)

One model per Skate 3 part (152 decks, 40 trucks, 71 wheels: the clean copies the game's shop shows), each with that
part's own texture. The textures are Skate 3's DXT5 data turned into DXT1 without touching a pixel's colour: Skate 3's
alpha channel is a gloss mask, which must not reach GTA's diffuse alpha, and a DXT5 colour block IS a DXT1 colour block
once its two end colours are in DXT1's order.

Also written: decks.lua (the catalogue for the scripts) and decks/ (catalog.json, the game's own shop thumbnails, deck
previews, brand logos, the plain decks' atlases) for the shop page.

Inputs: the dump's content\\createacharacter.big and big\\fedynamic.big, and the catalogue tables and decoded pictures
that the research step made from the same dump (RESEARCH below: catalog\\*.json, decks\\png\\...).

usage: python build_board.py [--slots 16] [--force]          (output: ~\\skate3-extract\\decks_build)
"""
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'decks'))
import eb_extract  # noqa: E402
import s3tex  # noqa: E402
from psg_mesh import PsgModel  # noqa: E402

DUMP = os.path.join(HERE, '..', '..', 'PS3_GAME', 'USRDIR', 'data')
import paths  # noqa: E402
RESEARCH = paths.work(r"research")
OUT = paths.work(r"decks_build")
CWTOOL = paths.CWTOOL

# GTA (x, y, z) = (-Sz, -Sx, Sy): Skate 3 model space is +Z nose, +X board left, +Y up. A pure rotation.
AXES = np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0]], float)
KICK = 0.0267          # metres the deck's tips rise above its flat top (measured on the mesh by the research step)
AREA = dict(x=3, y=262, w=449, h=247)   # the underside graphic's block in the 512 x 512 deck atlas (nose at the left)
LOD_DIST = 120
ARCHETYPE_FLAGS = 549453824             # v_res_skateboard's own archetype flags
MODELS = {'deck': 'SkateBoard/0x0000157603e38811.psg', 'truck': 'SkateTruck/0x0000157a03e38811.psg',
          'wheel': 'SkateWheel/0x0000157c03e38811.psg'}
# the words of Skate 3's own shop that the page shows (label id -> the page's key)
STRINGS = {'ID_CAC_SUBCATEGORY_BOARD_DECK': 'deck', 'ID_CAC_SUBCATEGORY_BOARD_TRUCKS': 'trucks',
           'ID_CAC_SUBCATEGORY_BOARD_WHEELS': 'wheels', 'ID_CAC_CATEGORY_SKATEBOARD': 'skateboard',
           'ID_CAC_FILTER_ALL': 'all', 'ID_CAC_FILTER_BRANDS': 'brands', 'ID_CAC_FILTER_OWNED': 'owned',
           'ID_CAC_FILTER_LOCKED': 'locked', 'ID_CAC_FILTER_PREFIX': 'filterPrefix',
           'ID_CAC_PRICETAG_ALREADYOWNED': 'alreadyOwned', 'ID_CAC_PRICETAG_COST': 'cost', 'ID_CAC_PRICETAG_FREE': 'free',
           'ID_CAC_PRICETAG_INSUFFICIENT': 'insufficient', 'ID_CAC_WALLET_TITLE': 'wallet',
           'ID_CAC_NOT_ENOUGH_CASH_TITLE': 'noCashTitle', 'ID_CAC_NOT_ENOUGH_CASH_DESC': 'noCashDesc'}


def log(*a):
    print(*a, flush=True)


def slug(s):
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', s.lower())).strip('_')


def part_id(kind, asset):
    """The game's material name without the model's prefix and the _material suffix: skateboard_big_script_material
    -> big_script."""
    s = asset.lower()
    for prefix in ('skateboard_', 'skatetruck_', 'skatewheel_'):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if s.endswith('_material'):
        s = s[:-len('_material')]
    return slug(s)


# ---------------------------------------------------------------------------------------------- the dump

class Archive:
    def __init__(self, path):
        self.f, entries = eb_extract.read_archive(path)
        self.by_name = {e[0].lower(): e for e in entries}

    def read(self, name):
        e = self.by_name[name.lower()]
        return eb_extract.extract(self.f, e[1], e[2], e[3])

    def names(self, part):
        return [e[0] for e in self.by_name.values() if part in e[0].lower()]


# ---------------------------------------------------------------------------------------------- textures

def opaque_dxt1(tex):
    """Skate 3's DXT5 levels as DXT1 with no transparency. A DXT5 colour block always has four colours; DXT1 reads the
    same eight bytes as four colours only when the first end colour is the larger number, so where it is not the two
    are swapped and every 2-bit index has its low bit flipped (0 <-> 1, 2 <-> 3: the same four colours). Two equal end
    colours make every index mean that one colour: all indices 0."""
    if tex['format'] == 'DXT1':
        levels = []
        for w, h, data in tex['levels']:
            b = np.frombuffer(data, np.uint8).reshape(-1, 8).copy()
            levels.append((w, h, _order(b).tobytes()))
        return dict(tex, levels=levels)
    assert tex['format'] == 'DXT5', tex['format']
    levels = []
    for w, h, data in tex['levels']:
        b = np.frombuffer(data, np.uint8).reshape(-1, 16)[:, 8:].copy()
        levels.append((w, h, _order(b).tobytes()))
    return dict(tex, format='DXT1', levels=levels)


def _order(b):
    c0 = b[:, 0].astype(np.uint32) | (b[:, 1].astype(np.uint32) << 8)
    c1 = b[:, 2].astype(np.uint32) | (b[:, 3].astype(np.uint32) << 8)
    idx = b[:, 4:8].copy().view('<u4')[:, 0]
    swap = c0 < c1
    idx = np.where(swap, idx ^ 0x55555555, idx)
    idx = np.where(c0 == c1, 0, idx).astype('<u4')
    lo, hi = np.minimum(c0, c1), np.maximum(c0, c1)
    out = np.empty_like(b)
    out[:, 0], out[:, 1] = hi & 0xFF, hi >> 8
    out[:, 2], out[:, 3] = lo & 0xFF, lo >> 8
    out[:, 4:8] = idx.view(np.uint8).reshape(-1, 4)
    return out


def dds_dxt1(tex):
    t = dict(tex, mips=len(tex['levels']))
    return s3tex.dds_bytes(t)


def dds_rgba(img):
    """An uncompressed 32-bit DDS with a full mip chain, from a pillow image (for pictures that are not Skate 3's)."""
    img = img.convert('RGBA')
    w, h = img.size
    levels = []
    while True:
        r, g, b, a = img.split()
        levels.append(Image.merge('RGBA', (b, g, r, a)).tobytes())
        if img.size == (1, 1):
            break
        img = img.resize((max(1, img.size[0] // 2), max(1, img.size[1] // 2)), Image.LANCZOS)
    hdr = b'DDS ' + struct.pack('<7I44x', 124, 0x0002100F, h, w, w * 4, 0, len(levels)) + \
        struct.pack('<2I4s5I', 32, 0x41, b'\0\0\0\0', 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000) + \
        struct.pack('<5I', 0x00401008, 0, 0, 0, 0)
    assert len(hdr) == 128
    return hdr + b''.join(levels), len(levels)


def tex_item(name, w, h, mips, fmt='D3DFMT_DXT1'):
    return ['   <Item>', '    <Name>%s</Name>' % name, '    <Unk32 value="128" />', '    <Usage>DIFFUSE</Usage>',
            '    <UsageFlags>X32, X64, X128, UNK24</UsageFlags>', '    <ExtraFlags value="0" />',
            '    <Width value="%d" />' % w, '    <Height value="%d" />' % h, '    <MipLevels value="%d" />' % mips,
            '    <Format>%s</Format>' % fmt, '    <FileName>%s.dds</FileName>' % name, '   </Item>']


# ---------------------------------------------------------------------------------------------- models

def load_mesh(path):
    m = PsgModel(path)
    return dict(pos=m.pos @ AXES.T, nrm=m.normal @ AXES.T, uv=m.uv, idx=m.indices.tolist(), tris=m.tris)


def box_item(lo, hi, material):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    full = hi - lo
    inertia = ((full[1] ** 2 + full[2] ** 2) / 12, (full[0] ** 2 + full[2] ** 2) / 12, (full[0] ** 2 + full[1] ** 2) / 12)
    return dict(c=(lo + hi) / 2, half=full / 2, vol=float(np.prod(full)), inertia=inertia, margin=float(full.min() / 8),
                material=material, radius=float(np.linalg.norm(full / 2)))


def bounds_xml(boxes, lo, hi):
    """A composite of boxes, laid out as CodeWalker writes v_res_skateboard's own (materials 69 / 93 as in that prop)."""
    c = (lo + hi) / 2
    vol = sum(b['vol'] for b in boxes)
    inertia = np.zeros(3)
    for b in boxes:
        d = b['c'] - c
        inertia += b['vol'] / vol * (np.array(b['inertia']) + np.array([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2,
                                                                       d[0] ** 2 + d[1] ** 2]))
    L = [' <Bounds type="Composite">', '  <BoxMin x="%.7g" y="%.7g" z="%.7g" />' % tuple(lo),
         '  <BoxMax x="%.7g" y="%.7g" z="%.7g" />' % tuple(hi), '  <BoxCenter x="%.7g" y="%.7g" z="%.7g" />' % tuple(c),
         '  <SphereCenter x="%.7g" y="%.7g" z="%.7g" />' % tuple(c),
         '  <SphereRadius value="%.7g" />' % float(np.linalg.norm((hi - lo) / 2)), '  <Margin value="0" />',
         '  <Volume value="%.7g" />' % vol, '  <Inertia x="%.7g" y="%.7g" z="%.7g" />' % tuple(inertia)]
    for tag in ('MaterialIndex', 'MaterialColourIndex', 'ProceduralID', 'RoomID', 'PedDensity', 'UnkFlags', 'PolyFlags'):
        L.append('  <%s value="0" />' % tag)
    L += ['  <UnkType value="1" />', '  <Children>']
    for b in boxes:
        h = b['half']
        L += ['   <Item type="Box">', '    <BoxMin x="%.7g" y="%.7g" z="%.7g" />' % tuple(-h),
              '    <BoxMax x="%.7g" y="%.7g" z="%.7g" />' % tuple(h), '    <BoxCenter x="0" y="0" z="0" />',
              '    <SphereCenter x="0" y="0" z="0" />', '    <SphereRadius value="%.7g" />' % b['radius'],
              '    <Margin value="%.7g" />' % b['margin'], '    <Volume value="%.7g" />' % b['vol'],
              '    <Inertia x="%.7g" y="%.7g" z="%.7g" />' % tuple(b['inertia']),
              '    <MaterialIndex value="%d" />' % b['material']]
        for tag, val in (('MaterialColourIndex', 0), ('ProceduralID', 0), ('RoomID', 0), ('PedDensity', 0),
                         ('UnkFlags', 18), ('PolyFlags', 0), ('UnkType', 1)):
            L.append('    <%s value="%d" />' % (tag, val))
        L += ['    <CompositeTransform>', '     1 0 0 0', '     0 1 0 0', '     0 0 1 0',
              '     %.7g %.7g %.7g 1' % tuple(b['c']), '    </CompositeTransform>',
              '    <CompositeFlags1>MAP_WEAPON, MAP_DYNAMIC, MAP_ANIMAL, MAP_COVER, MAP_VEHICLE</CompositeFlags1>',
              '    <CompositeFlags2>VEHICLE_NOT_BVH, VEHICLE_BVH, PED, RAGDOLL, ANIMAL, ANIMAL_RAGDOLL, OBJECT, PLANT, '
              'PROJECTILE, EXPLOSION, FORKLIFT_FORKS, TEST_WEAPON, TEST_CAMERA, TEST_AI, TEST_SCRIPT, '
              'TEST_VEHICLE_WHEEL, GLASS</CompositeFlags2>', '   </Item>']
    L += ['  </Children>', ' </Bounds>']
    return L


def drawable_xml(name, mesh, texname, tex, box, bounds):
    """One mesh, one 'default' shader. tex = (w, h, mips) of a texture embedded under texname, or None when the
    texture comes from the archetype's texture dictionary. box = (lo, hi) the drawable claims; bounds = collision XML."""
    lo, hi = box
    centre = (lo + hi) / 2
    radius = float(np.linalg.norm((hi - lo) / 2))
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<Drawable>', ' <Name>%s.#dr</Name>' % name,
         ' <BoundingSphereCenter x="%.6f" y="%.6f" z="%.6f" />' % tuple(centre),
         ' <BoundingSphereRadius value="%.6f" />' % radius,
         ' <BoundingBoxMin x="%.6f" y="%.6f" z="%.6f" />' % tuple(lo),
         ' <BoundingBoxMax x="%.6f" y="%.6f" z="%.6f" />' % tuple(hi)]
    for tag in ('LodDistHigh', 'LodDistMed', 'LodDistLow', 'LodDistVlow'):
        L.append(' <%s value="9998" />' % tag)
    L += [' <FlagsHigh value="1" />', ' <FlagsMed value="0" />', ' <FlagsLow value="0" />', ' <FlagsVlow value="0" />',
          ' <ShaderGroup>']
    if tex:
        L += ['  <TextureDictionary>'] + tex_item(texname, *tex) + ['  </TextureDictionary>']
    L += ['  <Shaders>', '   <Item>', '    <Name>default</Name>', '    <FileName>default.sps</FileName>',
          '    <RenderBucket value="0" />', '    <Parameters>', '     <Item name="DiffuseSampler" type="Texture">',
          '      <Name>%s</Name>' % texname, '     </Item>',
          '     <Item name="matMaterialColorScale" type="Vector" x="1" y="0" z="0" w="1" />',
          '     <Item name="HardAlphaBlend" type="Vector" x="1" y="0" z="0" w="0" />',
          '     <Item name="useTessellation" type="Vector" x="0" y="0" z="0" w="0" />',
          '     <Item name="wetnessMultiplier" type="Vector" x="1" y="0" z="0" w="0" />',
          '     <Item name="globalAnimUV1" type="Vector" x="0" y="1" z="0" w="0" />',
          '     <Item name="globalAnimUV0" type="Vector" x="1" y="0" z="0" w="0" />', '    </Parameters>', '   </Item>',
          '  </Shaders>', ' </ShaderGroup>', ' <DrawableModelsHigh>', '  <Item>', '   <RenderMask value="255" />',
          '   <Flags value="0" />', '   <HasSkin value="0" />', '   <BoneIndex value="0" />', '   <Unknown1 value="0" />',
          '   <Geometries>']
    plo, phi = mesh['pos'].min(0), mesh['pos'].max(0)
    L += ['    <Item>', '     <ShaderIndex value="0" />',
          '     <BoundingBoxMin x="%.7g" y="%.7g" z="%.7g" w="%.7g" />' % (plo[0], plo[1], plo[2], plo[0]),
          '     <BoundingBoxMax x="%.7g" y="%.7g" z="%.7g" w="%.7g" />' % (phi[0], phi[1], phi[2], phi[0]),
          '     <VertexBuffer>', '      <Flags value="0" />', '      <Layout type="GTAV1">', '       <Position />',
          '       <Normal />', '       <Colour0 />', '       <TexCoord0 />', '      </Layout>', '      <Data>']
    for q, n, uv in zip(mesh['pos'], mesh['nrm'], mesh['uv']):
        L.append('       %.7g %.7g %.7g   %.5f %.5f %.5f   255 255 255 255   %.6f %.6f' % (
            q[0], q[1], q[2], n[0], n[1], n[2], uv[0], uv[1]))
    L += ['      </Data>', '     </VertexBuffer>', '     <IndexBuffer>', '      <Data>']
    idx = mesh['idx']
    for k in range(0, len(idx), 24):
        L.append('       ' + ' '.join(str(v) for v in idx[k:k + 24]))
    L += ['      </Data>', '     </IndexBuffer>', '    </Item>', '   </Geometries>', '  </Item>', ' </DrawableModelsHigh>']
    L += bounds or []
    L += [' <Lights />', '</Drawable>']
    return '\n'.join(L) + '\n'


def archetype_xml(name, box, physics, txd=''):
    lo, hi = box
    centre = (lo + hi) / 2
    return ['  <Item type="CBaseArchetypeDef">', '   <lodDist value="%d" />' % LOD_DIST,
            '   <flags value="%d" />' % ARCHETYPE_FLAGS, '   <specialAttribute value="0" />',
            '   <bbMin x="%.6f" y="%.6f" z="%.6f" />' % tuple(lo), '   <bbMax x="%.6f" y="%.6f" z="%.6f" />' % tuple(hi),
            '   <bsCentre x="%.6f" y="%.6f" z="%.6f" />' % tuple(centre),
            '   <bsRadius value="%.6f" />' % float(np.linalg.norm((hi - lo) / 2)), '   <hdTextureDist value="5" />',
            '   <name>%s</name>' % name,
            '   <textureDictionary>%s</textureDictionary>' % txd if txd else '   <textureDictionary />',
            '   <clipDictionary />', '   <drawableDictionary />',
            # a drawable with collision of its own names itself here; without this a dropped board has nothing
            # registered to land on
            '   <physicsDictionary>%s</physicsDictionary>' % name if physics else '   <physicsDictionary />',
            '   <assetType>ASSET_TYPE_DRAWABLE</assetType>', '   <assetName>%s</assetName>' % name, '   <extensions />',
            '  </Item>']


def cw(cmd):
    r = subprocess.run([CWTOOL], input=json.dumps(cmd), capture_output=True, text=True)
    try:
        res = json.loads(r.stdout or '{}')
    except ValueError:
        res = {'error': (r.stdout or '')[:300]}
    if not (res.get('ok') or res.get('output')):
        raise RuntimeError('cwtool %s failed: %s %s' % (cmd, res, (r.stderr or '')[:300]))
    return res


# ---------------------------------------------------------------------------------------------- the build

def main():
    t0 = time.time()
    slots = int(sys.argv[sys.argv.index('--slots') + 1]) if '--slots' in sys.argv else 16
    force = '--force' in sys.argv
    gta, xml, web = os.path.join(OUT, 'gta'), os.path.join(OUT, 'xml'), os.path.join(OUT, 'web', 'decks')
    for d in (gta, xml, os.path.join(OUT, 'raw'), os.path.join(web, 'thumbs', 'deck'), os.path.join(web, 'thumbs', 'truck'),
              os.path.join(web, 'thumbs', 'wheel'), os.path.join(web, 'preview'), os.path.join(web, 'logos'),
              os.path.join(web, 'base')):
        os.makedirs(d, exist_ok=True)

    cac = Archive(os.path.join(DUMP, 'content', 'createacharacter.big'))
    strings = json.load(open(os.path.join(RESEARCH, 'catalog', 'strings_en.json'), encoding='utf-8'))
    cats = {k: json.load(open(os.path.join(RESEARCH, 'catalog', f), encoding='utf-8'))
            for k, f in (('deck', 'decks_catalog.json'), ('truck', 'trucks_catalog.json'), ('wheel', 'wheels_catalog.json'))}

    # the three meshes, in GTA's frame
    meshes = {}
    for kind, entry in MODELS.items():
        raw = os.path.join(OUT, 'raw', os.path.basename(entry))
        open(raw, 'wb').write(cac.read('data/content/createacharacter/model/cas_db/' + entry))
        meshes[kind] = load_mesh(raw)
    allp = np.concatenate([m['pos'] for m in meshes.values()])
    board_box = (allp.min(0), allp.max(0))
    deck = meshes['deck']['pos']
    hw = np.concatenate([meshes['truck']['pos'], meshes['wheel']['pos']])
    # collision of the whole board on the deck object: the deck, and a block under each end standing for that end's
    # truck and wheels down to the ground, so the board rests at wheel height
    boxes = [box_item(deck.min(0), deck.max(0), 69)]
    for sel in (hw[:, 0] > 0, hw[:, 0] < 0):
        q = hw[sel]
        boxes.append(box_item(q.min(0), [q[:, 0].max(), q[:, 1].max(), deck[:, 2].min()], 93))
    deck_bounds = bounds_xml(boxes, *board_box)
    log('meshes: deck %d, trucks %d, wheels %d vertices; board box %s .. %s' % (
        len(deck), len(meshes['truck']['pos']), len(meshes['wheel']['pos']),
        np.round(board_box[0], 4).tolist(), np.round(board_box[1], 4).tolist()))

    # the catalogue
    parts, seen = {'deck': [], 'truck': [], 'wheel': []}, set()
    brands = {}
    for kind, rows in cats.items():
        for r in rows:
            pid = part_id(kind, r['asset'])
            assert (kind, pid) not in seen, (kind, pid)
            seen.add((kind, pid))
            name = r.get('displayName') or r.get('nearMissDisplayName')   # (near miss: the game has no exact label)
            if kind == 'deck' and r.get('kind') == 'customizable':
                # the ten plain decks have no label of their own in the game: its name for the kind, and the colour
                # from the material name
                colour = re.sub(r'\d+$', '', pid.replace('stampable_', '')).replace('_', ' ').title()
                name = (strings.get('ID_CAC_PART_SKATEBOARD_STAMPABLE_SKATEBOARD_STAMPABLE_WHITE') or 'Skate') + ' ' + colour
            unlock = (r.get('unlock') or {}).get('condition') if isinstance(r.get('unlock'), dict) else None
            brand = r.get('brandId') or r.get('group') or ''
            if brand and r.get('brandLogo'):
                brands[brand] = r['brandLogo']
            parts[kind].append(dict(
                id=pid, model='s3_%s_%s' % (kind, pid), name=name or pid, brand=brand,
                brandName=r.get('brand') if r.get('brand') not in (None, '', 'Brandless') else False,
                price=int(r.get('price') or 0), unlock=unlock or False, plain=r.get('kind') == 'customizable',
                asset=r['asset'], model_name=r['model'], texture=r['diffuseTexture'], default=bool(r.get('isDefault'))))
        parts[kind].sort(key=lambda p: (p['brand'] or 'zzz', p['name'].lower()))
    default = {}
    for kind in parts:
        d = [p for p in parts[kind] if p['default']]
        default[kind] = (d[0] if d else parts[kind][0])['id']
    log('catalogue: %d decks, %d trucks, %d wheels; default %s' % (len(parts['deck']), len(parts['truck']),
                                                                  len(parts['wheel']), default))

    # models: XML + DDS, compiled only when their inputs changed
    stamp_path = os.path.join(OUT, 'stamps.json')
    stamps = {} if force or not os.path.exists(stamp_path) else json.load(open(stamp_path))
    code = hashlib.md5(open(os.path.abspath(__file__), 'rb').read()).hexdigest()
    built = 0
    archetypes = []

    def texture_of(tid):
        return opaque_dxt1(s3tex.read_texture(cac.read('data/content/createacharacter/texture/%s.psg' % tid)))

    def compile_model(name, kind, tex, texname, physics, txd=''):
        nonlocal built
        mesh = meshes['deck' if kind == 'slot' else kind]
        box = board_box if physics else (mesh['pos'].min(0), mesh['pos'].max(0))
        archetypes.extend(archetype_xml(name, box, physics, txd))
        key = '%s|%s|%s' % (code, tex['id'] if tex else txd, kind)
        out = os.path.join(gta, name + '.ydr')
        if stamps.get(name) == key and os.path.exists(out):
            return
        info = None
        if tex:
            os.makedirs(os.path.join(xml, name), exist_ok=True)
            open(os.path.join(xml, name, texname + '.dds'), 'wb').write(dds_dxt1(tex))
            info = (tex['width'], tex['height'], len(tex['levels']))
        path = os.path.join(xml, name + '.ydr.xml')
        open(path, 'w', encoding='utf-8', newline='\n').write(
            drawable_xml(name, mesh, texname, info, box, deck_bounds if physics else None))
        cw({'cmd': 'tobin', 'in': path, 'out': out})
        stamps[name] = key
        built += 1
        if built % 40 == 0:
            log('  %d models compiled ...' % built)

    for kind in ('deck', 'truck', 'wheel'):
        for p in parts[kind]:
            tex = dict(texture_of(p['texture']), id=p['texture'])
            compile_model(p['model'], kind, tex, 's3_' + kind, physics=kind == 'deck')

    # the slots for players' own pictures: the deck mesh, its texture in the shared dictionary
    white = next((p for p in parts['deck'] if p['plain'] and 'white' in p['id']), None) or \
        next(p for p in parts['deck'] if p['plain'])
    slot_names = ['s3_custom_%02d' % k for k in range(1, slots + 1)]
    for n in slot_names:
        compile_model(n, 'slot', None, n, physics=True, txd='s3_custom_slots')
    wtex = texture_of(white['texture'])
    os.makedirs(os.path.join(xml, 's3_custom_slots'), exist_ok=True)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<TextureDictionary>']
    for n in slot_names:
        open(os.path.join(xml, 's3_custom_slots', n + '.dds'), 'wb').write(dds_dxt1(wtex))
        L += tex_item(n, wtex['width'], wtex['height'], len(wtex['levels']))
    L.append('</TextureDictionary>')
    ytd = os.path.join(xml, 's3_custom_slots.ytd.xml')
    open(ytd, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    cw({'cmd': 'tobin', 'in': ytd, 'out': os.path.join(gta, 's3_custom_slots.ytd')})

    Y = ['<?xml version="1.0" encoding="UTF-8"?>', '<CMapTypes>', ' <extensions />', ' <archetypes>'] + archetypes + \
        [' </archetypes>', ' <name>s3_boards</name>', ' <dependencies />',
         ' <compositeEntityTypes itemType="CCompositeEntityType" />', '</CMapTypes>']
    ytyp = os.path.join(xml, 's3_boards.ytyp.xml')
    open(ytyp, 'w', encoding='utf-8', newline='\n').write('\n'.join(Y) + '\n')
    cw({'cmd': 'tobin', 'in': ytyp, 'out': os.path.join(gta, 's3_boards.ytyp')})
    json.dump(stamps, open(stamp_path, 'w'))
    # models of parts that are no longer in the catalogue go
    wanted = {p['model'] for k in parts for p in parts[k]} | set(slot_names)
    for f in os.listdir(gta):
        if f.endswith('.ydr') and f[:-4] not in wanted:
            os.remove(os.path.join(gta, f))

    # pictures for the page: the game's own shop thumbnails, the decks' undersides, brand logos, the plain decks
    thumbs = os.path.join(RESEARCH, 'decks', 'png', 'fe_thumbs')
    folder = {'deck': 'skateboard', 'truck': 'skatetruck', 'wheel': 'skatewheel'}
    for kind in parts:
        for p in parts[kind]:
            src = os.path.join(thumbs, folder[kind], ('%s_%s.png' % (p['model_name'], p['asset'])).lower())
            dst = os.path.join(web, 'thumbs', kind, p['id'] + '.png')
            p['thumb'] = os.path.exists(src)
            if p['thumb'] and not os.path.exists(dst):
                Image.open(src).save(dst)
    for p in parts['deck']:
        src = os.path.join(RESEARCH, 'decks', 'png', 'decks_bottom', p['asset'] + '.png')
        dst = os.path.join(web, 'preview', p['id'] + '.webp')   # (with the deck's own outline: the picture has alpha)
        p['preview'] = os.path.exists(src)
        if p['preview'] and not os.path.exists(dst):
            im = Image.open(src).convert('RGBA')
            im.resize((640, round(640 * im.size[1] / im.size[0])), Image.LANCZOS).save(dst, quality=88)
        if p['plain']:
            dst = os.path.join(web, 'base', p['id'] + '.png')
            if not os.path.exists(dst):
                rgba = s3tex.decode_level(s3tex.read_texture(
                    cac.read('data/content/createacharacter/texture/%s.psg' % p['texture'])), 0)
                Image.fromarray(rgba[:, :, :3]).save(dst)
    fe = Archive(os.path.join(DUMP, 'big', 'fedynamic.big'))
    logos = {}
    for brand, entry in brands.items():
        dst = os.path.join(web, 'logos', slug(brand) + '.png')
        try:
            if not os.path.exists(dst):
                Image.fromarray(s3tex.decode_level(s3tex.read_texture(fe.read(entry)), 0)).save(dst)
            logos[brand] = 'decks/logos/%s.png' % slug(brand)
        except (KeyError, s3tex.Rw4Error) as e:
            log('  no logo for %s: %s' % (brand, e))

    # the catalogue for the page and for the scripts
    def row(kind, p):
        r = dict(id=p['id'], name=p['name'], brand=p['brand'], brandName=p['brandName'] or None, price=p['price'],
                 unlock=p['unlock'] or None, thumb='decks/thumbs/%s/%s.png' % (kind, p['id']) if p['thumb'] else None,
                 logo=logos.get(p['brand']))
        if kind == 'deck':
            r.update(plain=p['plain'], preview='decks/preview/%s.webp' % p['id'] if p['preview'] else None)
        return r

    bases = [p for p in parts['deck'] if p['plain']]
    catalog = dict(
        version=2, default=default, strings={v: strings[k] for k, v in STRINGS.items() if k in strings},
        decks=[row('deck', p) for p in parts['deck']], trucks=[row('truck', p) for p in parts['truck']],
        wheels=[row('wheel', p) for p in parts['wheel']],
        custom=dict(size=512, area=AREA, bases=[dict(id=p['id'], name=p['name'], atlas='decks/base/%s.png' % p['id'])
                                               for p in bases]))
    json.dump(catalog, open(os.path.join(web, 'catalog.json'), 'w', encoding='utf-8'), indent=1)

    def lua(v):
        if v is False or v is None:
            return 'false'
        if v is True:
            return 'true'
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace('\\', '\\\\').replace("'", "\\'") + "'"

    def lua_rows(kind, extra=()):
        out = []
        for p in parts[kind]:
            f = ['id = %s' % lua(p['id']), 'model = %s' % lua(p['model']), 'name = %s' % lua(p['name']),
                 'brand = %s' % lua(p['brand']), 'brandName = %s' % lua(p['brandName']), 'price = %d' % p['price'],
                 'unlock = %s' % lua(p['unlock'])] + ['%s = %s' % (k, lua(p[k])) for k in extra]
            out.append('    { ' + ', '.join(f) + ' },')
        return out

    L = ["-- Skate 3's own board parts, from your copy of the game (generated by skate3-sp/tools/build_board.py).",
         '-- stock = the decks; every part is its own model. custom = the models whose deck texture a script replaces.',
         'Skate3Decks = {', '  version = 2,', '  kick = %r,' % KICK,
         '  default = { deck = %s, truck = %s, wheel = %s },' % (lua(default['deck']), lua(default['truck']), lua(default['wheel'])),
         '  stock = {'] + lua_rows('deck', ('plain',)) + ['  },', '  trucks = {'] + lua_rows('truck') + ['  },',
         '  wheels = {'] + lua_rows('wheel') + ['  },', '  custom = {',
         '    slots = { ' + ', '.join(lua(n) for n in slot_names) + ' },', "    txd = 's3_custom_slots',",
         '    textures = { ' + ', '.join(lua(n) for n in slot_names) + ' },', '    size = 512,',
         '    area = { x = %(x)d, y = %(y)d, w = %(w)d, h = %(h)d },' % AREA, '    bases = {'] + \
        ['      { id = %s, name = %s, model = %s },' % (lua(p['id']), lua(p['name']), lua(p['model'])) for p in bases] + \
        ['    },', '  },', '}']
    open(os.path.join(OUT, 'decks.lua'), 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')

    size = sum(os.path.getsize(os.path.join(gta, f)) for f in os.listdir(gta))
    log('board built: %d models compiled this run (%d files, %.1f MB in %s), %d thumbnails, %d logos, %.0f s' % (
        built, len(os.listdir(gta)), size / 1e6, gta, sum(p['thumb'] for k in parts for p in parts[k]), len(logos),
        time.time() - t0))
    return dict(parts=parts, slots=slot_names, default=default, gta=gta, web=os.path.join(OUT, 'web'),
                lua=os.path.join(OUT, 'decks.lua'))


if __name__ == '__main__':
    main()
