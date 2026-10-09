"""Skate 3 (PS3) texture decoder: RenderWare 4 arena (.psg) -> PNG / DDS.

Every texture in createacharacter.big / parkassets.big is one RW4 arena that holds one
rw::graphics::Texture object (type id 0x000200E8, a CellGcmTexture header) and one pixel
buffer (base resource, type id 0x00010034). See NOTES.md for the byte layout.

usage:
  python s3tex.py info   <file.psg | dir> [...]              print header fields (tab separated)
  python s3tex.py decode <file.psg | dir> [...] -o OUT_DIR   write name.png (RGB) + name.alpha.png (the alpha channel)
         options:  --rgba        write ONE RGBA png instead (right for the menu thumbnails, whose alpha is transparency;
                                 on deck / truck / wheel textures alpha is a gloss mask and an RGBA png looks washed out)
                   --no-alpha    RGB only, no .alpha.png
                   --mip N       decode mip level N instead of 0
                   --all-mips    write every mip level (name.mipN.png)
                   --dds         also write a .dds (the DXT payload with all mips behind a DDS header)
  python s3tex.py big    <archive.big> <id-or-substring> [...] -o OUT_DIR [same options]
                                 extract matching entries straight from an EB .big and decode them
                                 (needs eb_extract.py next to this file or in the project's tools folder).
                                 At least one substring is required; pass --everything to decode the whole archive.

Only numpy and pillow are needed. Pixel decoding is done here (DXT1 / DXT3 / DXT5, A8R8G8B8);
nothing is delegated to an external tool.
"""
import os
import struct
import sys

import numpy as np
from PIL import Image

RW4_MAGIC = b'\x89RW4ps3\x00\r\n\x1a\n'
TYPE_TEXTURE = 0x000200E8
TYPE_BASERESOURCE_LO, TYPE_BASERESOURCE_HI = 0x00010030, 0x0001003F

# CELL_GCM_TEXTURE_* (low 5 bits + 0x80); flags: 0x20 = LN (linear, not swizzled), 0x40 = UN (unnormalised)
GCM_FORMATS = {
    0x81: 'B8', 0x82: 'A1R5G5B5', 0x83: 'A4R4G4B4', 0x84: 'R5G6B5', 0x85: 'A8R8G8B8',
    0x86: 'DXT1', 0x87: 'DXT3', 0x88: 'DXT5', 0x8B: 'G8B8',
}


class Rw4Error(Exception):
    pass


def parse_arena(b):
    """Return (header dict, [dictionary entries]). Each entry: dict(ptr, size, align, type_index, type_id, file_off)."""
    if b[:12] != RW4_MAGIC:
        raise Rw4Error('not an RW4 PS3 arena (magic %r)' % b[:12])
    if b[12] != 1:
        raise Rw4Error('not big-endian')
    (arena_id, num_entries, num_used, alignment, virt, dict_start, sections, base) = struct.unpack_from('>8I', b, 0x1C)
    res_desc = [struct.unpack_from('>2I', b, 0x44 + 8 * i) for i in range(6)]
    main_size = res_desc[0][0]          # header + objects; base resources (pixel data) start here
    entries = []
    for i in range(num_entries):
        ptr, reloc, size, align, type_index, type_id = struct.unpack_from('>6I', b, dict_start + 24 * i)
        is_base = TYPE_BASERESOURCE_LO <= type_id <= TYPE_BASERESOURCE_HI
        entries.append(dict(ptr=ptr, size=size, align=align, type_index=type_index, type_id=type_id,
                            file_off=ptr + (main_size if is_base else 0), is_base=is_base))
    hdr = dict(version=b[16:19].decode('ascii', 'replace'), arena_id=arena_id, num_entries=num_entries,
               dict_start=dict_start, sections=sections, main_size=main_size, res_desc=res_desc)
    return hdr, entries


def mip_size(fmt, w, h):
    if fmt in ('DXT1',):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if fmt in ('DXT3', 'DXT5'):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    if fmt == 'A8R8G8B8':
        return w * h * 4
    if fmt in ('A1R5G5B5', 'A4R4G4B4', 'R5G6B5', 'G8B8'):
        return w * h * 2
    if fmt == 'B8':
        return w * h
    raise Rw4Error('unsupported format %s' % fmt)


def read_texture(b):
    """Parse one texture arena. Returns dict with header fields and 'mips': [(w, h, bytes)]."""
    hdr, entries = parse_arena(b)
    tex = [e for e in entries if e['type_id'] == TYPE_TEXTURE]
    if not tex:
        raise Rw4Error('no Texture object (0x000200E8) in arena; types: %s' %
                       ', '.join('0x%08x' % e['type_id'] for e in entries))
    t = tex[0]
    o = t['file_off']
    (fmt_raw, mips, dimension, cubemap, remap, width, height, depth, location, _pad, pitch, offset,
     buffer_index, store_type, store_flags) = struct.unpack_from('>BBBBIHHHBBIIIII', b, o)
    fmt = GCM_FORMATS.get(fmt_raw & 0x9F)
    if fmt is None:
        raise Rw4Error('unknown CellGcm format byte 0x%02x' % fmt_raw)
    linear = bool(fmt_raw & 0x20)
    if buffer_index >= len(entries) or not entries[buffer_index]['is_base']:
        # fall back: first base resource
        cands = [e for e in entries if e['is_base']]
        if not cands:
            raise Rw4Error('no pixel buffer in arena')
        buf = cands[0]
    else:
        buf = entries[buffer_index]
    data = b[buf['file_off']:buf['file_off'] + buf['size']]
    faces = 6 if cubemap else 1
    levels = []
    p = 0
    w, h = width, height
    for i in range(mips):
        n = mip_size(fmt, w, h)
        if p + n > len(data):
            break
        levels.append((w, h, data[p:p + n]))
        p += n
        w, h = max(1, w // 2), max(1, h // 2)
    name = None
    for e in entries:
        if e['type_id'] == 0x00EB000B:   # table of contents: holds "<id>.Texture"
            raw = b[e['file_off']:e['file_off'] + e['size']]
            k = raw.find(b'0x')
            if k >= 0:
                name = raw[k:].split(b'\0')[0].decode('latin-1')
    return dict(format=fmt, format_raw=fmt_raw, linear=linear, mips=len(levels), mips_declared=mips,
                dimension=dimension, cubemap=cubemap, remap=remap, width=width, height=height, depth=depth,
                location=location, pitch=pitch, offset=offset, data_size=buf['size'], data_used=p * faces,
                toc_name=name, levels=levels, payload=data, arena=hdr)


# ---------------------------------------------------------------- pixel decoders (numpy)

def _colour_table(c0, c1, dxt1):
    """c0, c1: uint16 arrays (n,). Returns (n, 4, 4) uint8 RGBA palette."""
    def rgb(c):
        r = (c >> 11) & 31
        g = (c >> 5) & 63
        bl = c & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (bl << 3) | (bl >> 2)], -1).astype(np.int32)
    p0, p1 = rgb(c0), rgb(c1)
    n = len(c0)
    pal = np.zeros((n, 4, 4), np.int32)
    pal[:, 0, :3] = p0
    pal[:, 1, :3] = p1
    pal[:, :, 3] = 255
    four = np.ones(n, bool) if not dxt1 else (c0 > c1)
    f = four[:, None]
    pal[:, 2, :3] = np.where(f, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(f, (p0 + 2 * p1) // 3, 0)
    if dxt1:
        pal[:, 3, 3] = np.where(four, 255, 0)
    return pal.astype(np.uint8)


def _blocks_to_image(px, bw, bh, w, h):
    """px: (n, 4, 4, C) -> (h, w, C)"""
    c = px.shape[-1]
    img = px.reshape(bh, bw, 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, c)
    return img[:h, :w]


def _colour_block(blk, dxt1):
    """blk: (n, 8) uint8. Returns (n, 4, 4, 4) RGBA."""
    c0 = blk[:, 0].astype(np.uint16) | (blk[:, 1].astype(np.uint16) << 8)
    c1 = blk[:, 2].astype(np.uint16) | (blk[:, 3].astype(np.uint16) << 8)
    pal = _colour_table(c0, c1, dxt1)
    bits = blk[:, 4:8]                                   # one byte per row, 2 bits per pixel, LSB first
    idx = np.stack([(bits >> (2 * i)) & 3 for i in range(4)], -1)   # (n, 4 rows, 4 cols)
    n = len(blk)
    return pal[np.arange(n)[:, None, None], idx]


def decode_dxt1(data, w, h):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    blk = np.frombuffer(data, np.uint8, bw * bh * 8).reshape(-1, 8)
    return _blocks_to_image(_colour_block(blk, True), bw, bh, w, h)


def decode_dxt3(data, w, h):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    blk = np.frombuffer(data, np.uint8, bw * bh * 16).reshape(-1, 16)
    px = _colour_block(blk[:, 8:], False).copy()
    a = blk[:, :8].reshape(-1, 4, 2)
    lo = a[:, :, 0]
    hi = a[:, :, 1]
    al = np.stack([lo & 15, lo >> 4, hi & 15, hi >> 4], -1)       # (n, 4, 4)
    px[..., 3] = (al * 17).astype(np.uint8)
    return _blocks_to_image(px, bw, bh, w, h)


def decode_dxt5(data, w, h):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    blk = np.frombuffer(data, np.uint8, bw * bh * 16).reshape(-1, 16)
    px = _colour_block(blk[:, 8:], False).copy()
    a0 = blk[:, 0].astype(np.int32)
    a1 = blk[:, 1].astype(np.int32)
    n = len(blk)
    tab = np.zeros((n, 8), np.int32)
    tab[:, 0], tab[:, 1] = a0, a1
    eight = a0 > a1
    for i in range(1, 7):
        tab[:, i + 1] = np.where(eight, ((7 - i) * a0 + i * a1) // 7, 0)
    for i in range(1, 5):
        tab[:, i + 1] = np.where(eight, tab[:, i + 1], ((5 - i) * a0 + i * a1) // 5)
    tab[:, 6] = np.where(eight, tab[:, 6], 0)
    tab[:, 7] = np.where(eight, tab[:, 7], 255)
    bits = np.zeros(n, np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    idx = np.stack([(bits >> np.uint64(3 * i)) & np.uint64(7) for i in range(16)], -1).astype(np.int64).reshape(n, 4, 4)
    px[..., 3] = tab[np.arange(n)[:, None, None], idx].astype(np.uint8)
    return _blocks_to_image(px, bw, bh, w, h)


def _unswizzle(arr, w, h):
    """Morton (Z-order) -> linear, for power-of-two PS3 swizzled surfaces. arr: (w*h, C)."""
    ys, xs = np.mgrid[0:h, 0:w]
    idx = np.zeros((h, w), np.int64)
    bit = 0
    xb = yb = 0
    mw, mh = w, h
    while mw > 1 or mh > 1:
        if mw > 1:
            idx |= ((xs >> xb) & 1) << bit
            bit += 1
            xb += 1
            mw >>= 1
        if mh > 1:
            idx |= ((ys >> yb) & 1) << bit
            bit += 1
            yb += 1
            mh >>= 1
    return arr[idx]


def decode_level(tex, level=0):
    """Return an (h, w, 4) uint8 RGBA array for one mip level."""
    w, h, data = tex['levels'][level]
    fmt = tex['format']
    if fmt == 'DXT1':
        return decode_dxt1(data, w, h)
    if fmt == 'DXT3':
        return decode_dxt3(data, w, h)
    if fmt == 'DXT5':
        return decode_dxt5(data, w, h)
    if fmt == 'A8R8G8B8':
        a = np.frombuffer(data, np.uint8, w * h * 4).reshape(-1, 4)
        a = a[:, [1, 2, 3, 0]]                      # ARGB (big-endian word) -> RGBA
        if tex['linear']:
            return a.reshape(h, w, 4)
        return _unswizzle(a, w, h)
    if fmt == 'B8':
        a = np.frombuffer(data, np.uint8, w * h)
        a = a.reshape(h, w) if tex['linear'] else _unswizzle(a.reshape(-1, 1), w, h)[..., 0]
        return np.stack([a, a, a, np.full_like(a, 255)], -1)
    raise Rw4Error('no pixel decoder for %s' % fmt)


# ---------------------------------------------------------------- DDS writer

def dds_bytes(tex):
    fmt = tex['format']
    w, h = tex['width'], tex['height']
    fourcc = {'DXT1': b'DXT1', 'DXT3': b'DXT3', 'DXT5': b'DXT5'}.get(fmt)
    if fourcc is None:
        raise Rw4Error('DDS export only for DXT formats (got %s)' % fmt)
    payload = b''.join(l[2] for l in tex['levels'])
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if tex['mips'] > 1 else 0)
    caps = 0x1000 | (0x400008 if tex['mips'] > 1 else 0)
    hdr = struct.pack('<4sIIIIIII', b'DDS ', 124, flags, h, w, len(tex['levels'][0][2]), 0, tex['mips'])
    hdr += b'\0' * 44
    hdr += struct.pack('<II4sIIIII', 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    hdr += struct.pack('<IIIII', caps, 0, 0, 0, 0)
    assert len(hdr) == 128
    return hdr + payload


# ---------------------------------------------------------------- command line

def iter_inputs(args):
    for a in args:
        if os.path.isdir(a):
            for root, _d, files in os.walk(a):
                for fn in sorted(files):
                    if fn.lower().endswith(('.psg', '.rx2', '.rpsgl', '.rps3')):
                        yield os.path.join(root, fn)
        else:
            yield a


def info_line(path, tex):
    return '\t'.join(str(x) for x in (
        os.path.basename(path), tex['format'], '0x%02x' % tex['format_raw'], tex['width'], tex['height'],
        tex['mips'], 'cube' if tex['cubemap'] else '2d', 'remap=0x%04x' % tex['remap'], 'pitch=%d' % tex['pitch'],
        'data=%d' % tex['data_size'], 'used=%d' % tex['data_used'], tex['toc_name'] or ''))


def write_outputs(name, b, out_dir, opts):
    tex = read_texture(b)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, os.path.splitext(os.path.basename(name))[0])
    levels = range(tex['mips']) if opts['all_mips'] else [min(opts['mip'], tex['mips'] - 1)]
    for lv in levels:
        img = decode_level(tex, lv)
        suffix = '.mip%d' % lv if (opts['all_mips'] or opts['mip']) else ''
        if opts['alpha']:
            Image.fromarray(np.ascontiguousarray(img[..., 3]), 'L').save(stem + suffix + '.alpha.png')
        if opts['rgba']:
            Image.fromarray(np.ascontiguousarray(img), 'RGBA').save(stem + suffix + '.png')
        else:
            Image.fromarray(np.ascontiguousarray(img[..., :3]), 'RGB').save(stem + suffix + '.png')
    if opts['dds']:
        open(stem + '.dds', 'wb').write(dds_bytes(tex))
    return tex


def load_eb_extract():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.join(here, 'tools'), os.path.join(here, '..')):
        if os.path.exists(os.path.join(d, 'eb_extract.py')):
            sys.path.insert(0, d)
            import eb_extract
            return eb_extract
    raise SystemExit('eb_extract.py not found (put it next to s3tex.py)')


def main(argv):
    if len(argv) < 2 or argv[0] not in ('info', 'decode', 'big'):
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    opts = dict(mip=0, all_mips=False, dds=False, rgba=False, alpha=True)
    everything = False
    out_dir = '.'
    pos = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == '-o':
            out_dir = rest[i + 1]
            i += 1
        elif a == '--mip':
            opts['mip'] = int(rest[i + 1])
            i += 1
        elif a == '--all-mips':
            opts['all_mips'] = True
        elif a == '--dds':
            opts['dds'] = True
        elif a == '--rgba':
            opts['rgba'] = True
            opts['alpha'] = False
        elif a in ('--no-alpha', '--rgb'):
            opts['alpha'] = False
        elif a == '--alpha':
            opts['alpha'] = True
        elif a == '--everything':
            everything = True
        else:
            pos.append(a)
        i += 1
    bad = 0
    if cmd == 'info':
        for p in iter_inputs(pos):
            try:
                print(info_line(p, read_texture(open(p, 'rb').read())))
            except Rw4Error as e:
                bad += 1
                print('%s\tERROR %s' % (os.path.basename(p), e))
    elif cmd == 'decode':
        for p in iter_inputs(pos):
            try:
                tex = write_outputs(p, open(p, 'rb').read(), out_dir, opts)
                print(info_line(p, tex))
            except Rw4Error as e:
                bad += 1
                print('%s\tERROR %s' % (os.path.basename(p), e))
    else:
        eb = load_eb_extract()
        f, entries = eb.read_archive(pos[0])
        pats = [s.lower() for s in pos[1:]]
        if not pats and not everything:
            print('refusing to decode the whole archive: give a name / id substring, or --everything')
            return 1
        for name, off, csize, size in entries:
            if pats and not any(s in name.lower() for s in pats):
                continue
            try:
                tex = write_outputs(name, eb.extract(f, off, csize, size), out_dir, opts)
                print(info_line(name, tex))
            except Rw4Error as e:
                bad += 1
                print('%s\tERROR %s' % (name, e))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
