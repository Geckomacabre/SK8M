"""Skate 3 (PS3) RW4 .psg model reader: vertex buffer, index buffer, vertex descriptor, bones, material.

Everything here was checked against the real board files (see NOTES.md for the proofs):
  VertexBuffer  (type 0x000200ea, 16 bytes):  u32 baseResourceDictIndex, u32 offset, u32 byteSize, u32 0
  IndexBuffer   (type 0x000200eb, 20 bytes):  u32 baseResourceDictIndex, u32 offset, u32 numIndices, u32 2 (=u16), u8 1, pad
  VertexDescriptor (type 0x000200e9): 16 byte header (u16 numElements at +0x0A), then numElements x 8 bytes:
        u8 gcmType, u8 count, u16 offset, u16 stride, u8 attribute, u8 1
        gcmType 1 = s16 normalised, 6 = CMP packed 11:11:10 signed normalised, 7 = u8 x4
        attribute 0 position, 1 blend weight, 7 blend indices, 8.. texcoord0.., 14 tangent, 15 normal (proved: matches face normals)
  position = s16 xyz / 16384 + (0, 0.8, 0)   (4th short = id of the welded position, not a coordinate)
  uv       = s16 / 32768                      (v = 0 is the first texel row of the texture, DirectX style)
  mesh/part  (type 0x00eb0023): bbox min/max (2 x 4 floats), then links; +0x64 u32 numIndices, +0x68 u8 primitive (5 = triangle list)
  skeleton   (type 0x00eb0001): bbox, u32 offMatrices(+0x20) offIds offNameOffs offNames, u16 numBones(+0x30) ...
               4x4 float inverse bind matrices (row vectors, translation in the last row), bone names
  material   (type 0x00eb0005): string table with Name, AttribulatorMaterialName and channel -> texture id pairs
"""
import re
import struct

import numpy as np

from rw4_arena import Arena

POS_SCALE = 1.0 / 16384.0
POS_OFFSET = np.array([0.0, 0.8, 0.0])
UV_SCALE = 1.0 / 32768.0


def _cmp(v):
    """CELL_GCM_VERTEX_CMP: x 11 bits (low), y 11 bits, z 10 bits (high), signed normalised"""
    v = v.astype(np.int64)
    x = v & 0x7FF
    y = (v >> 11) & 0x7FF
    z = (v >> 22) & 0x3FF
    x = np.where(x >= 0x400, x - 0x800, x) / 1023.0
    y = np.where(y >= 0x400, y - 0x800, y) / 1023.0
    z = np.where(z >= 0x200, z - 0x400, z) / 511.0
    return np.stack([x, y, z], axis=1)


class PsgModel:
    def __init__(self, path, data=None):
        self.path = path
        if data is None:
            data = open(path, 'rb').read()
        self.data = data
        a = self.arena = Arena(data)
        self.gfx = len(data) - a.res_desc[5][0]  # graphics block = the last res_desc[5].size bytes of the file

        vd = a.by_type(0x000200e9)[0]
        d = data[vd['ptr']:vd['ptr'] + vd['size']]
        n_el = struct.unpack_from('>H', d, 0x0A)[0]
        self.elements = [struct.unpack_from('>BBHHBB', d, 0x10 + 8 * i) for i in range(n_el)]
        self.stride = self.elements[0][3]

        vb = a.by_type(0x000200ea)[0]
        res_i, off, size, _ = struct.unpack_from('>4I', data, vb['ptr'])
        vo = self.gfx + a.entries[res_i]['ptr'] + off
        self.nverts = size // self.stride
        raw = np.frombuffer(data, dtype=np.uint8, count=self.nverts * self.stride, offset=vo).reshape(self.nverts, self.stride)
        self.raw = raw

        ib = a.by_type(0x000200eb)[0]
        res_i, off, n_idx, fmt = struct.unpack_from('>4I', data, ib['ptr'])
        io = self.gfx + a.entries[res_i]['ptr'] + off
        self.indices = np.frombuffer(data, dtype='>u2', count=n_idx, offset=io).astype(np.int32)
        self.tris = self.indices.reshape(-1, 3)

        self.attrs = {}
        for t, n, off, stride, attr, _x in self.elements:
            if t == 1:
                v = raw[:, off:off + 2 * n].copy().view('>i2').astype(np.float64)
            elif t == 6:
                v = _cmp(raw[:, off:off + 4].copy().view('>u4')[:, 0])
            elif t == 7:
                v = raw[:, off:off + n].astype(np.int32)
            elif t == 2:
                v = raw[:, off:off + 4 * n].copy().view('>f4').astype(np.float64)
            elif t == 3:
                v = raw[:, off:off + 2 * n].copy().view('>f2').astype(np.float64)
            else:
                raise ValueError('vertex type %d' % t)
            self.attrs[attr] = v
        p = self.attrs[0]
        self.pos_id = p[:, 3].astype(np.int32)
        self.pos = p[:, :3] * POS_SCALE + POS_OFFSET
        self.uv = self.attrs[8] * UV_SCALE
        # further UV sets: attr 9 (float x2, not scaled) is the stamp / logo UV of the "stampable" materials
        etype = {e[4]: e[0] for e in self.elements}
        self.uv_sets = {k - 8: self.attrs[k] * (UV_SCALE if etype[k] == 1 else 1.0)
                        for k in self.attrs if 8 <= k <= 13 and self.attrs[k].shape[1] == 2}
        # attr 14 = tangent, attr 15 = binormal; the normal is their cross product (proved with probe_normals.py:
        # it matches the geometric face normals, and equals the explicit attr 2 normal of the stampable board)
        self.tangent = self.attrs.get(14)
        self.binormal = self.attrs.get(15)
        if 2 in self.attrs:
            self.normal = self.attrs[2]
        else:
            n = np.cross(self.tangent, self.binormal)
            self.normal = n / np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
        self.bone_idx = self.attrs.get(7)
        self.bone_wgt = self.attrs.get(1)

        m = a.by_type(0x00eb0023)[0]
        o = m['ptr']
        self.bbox = np.array(struct.unpack_from('>8f', data, o)).reshape(2, 4)[:, :3]
        self.mesh_raw = data[o:o + m['size']]
        self._skeleton()
        # bone palette of the mesh: u32 count at +0x48, u32 offset at +0x4C, u16 skeleton bone index each;
        # the vertex blend index (4th byte of attr 7, weight 255 in the 4th byte of attr 1) indexes this palette
        npal, offpal = struct.unpack_from('>2I', data, o + 0x48)
        self.palette = list(struct.unpack_from('>%dH' % npal, data, o + offpal))
        self.vert_bone = np.array([self.palette[i] for i in self.bone_idx[:, 3]])
        self._material()
        nm = a.by_type(0x00eb000d)
        self.asset_name = ''
        if nm:
            s = data[nm[0]['ptr']:nm[0]['ptr'] + nm[0]['size']]
            mm = re.search(rb'[A-Za-z_][\x20-\x7e]{6,}', s[0xC0:])
            self.asset_name = mm.group(0).decode() if mm else ''

    def _skeleton(self):
        a, data = self.arena, self.data
        e = a.by_type(0x00eb0001)[0]
        o = e['ptr']
        off_mtx, off_ids, off_nameoffs, off_names = struct.unpack_from('>4I', data, o + 0x20)
        counts = struct.unpack_from('>4H', data, o + 0x30)
        nb = counts[0] if False else (off_ids - off_mtx) // 64
        self.skel_counts = counts
        self.bones = []
        for i in range(nb):
            mtx = np.array(struct.unpack_from('>16f', data, o + off_mtx + 64 * i)).reshape(4, 4)
            noff = struct.unpack_from('>I', data, o + off_nameoffs + 4 * i)[0]
            name = data[o + noff:data.index(b'\0', o + noff)].decode()
            bind = np.linalg.inv(mtx)  # bone -> model
            self.bones.append(dict(name=name, inv_bind=mtx, bind=bind, pos=bind[3, :3].copy()))
        self.skel_ids = struct.unpack_from('>2I', data, o + off_ids)

    def _material(self):
        a, data = self.arena, self.data
        e = a.by_type(0x00eb0005)[0]
        blob = data[e['ptr']:e['ptr'] + e['size']]
        i = blob.find(b'Name\0')
        strs = [s.decode('latin-1') for s in blob[i:].split(b'\0') if s]
        self.material = {}
        for k in range(0, len(strs) - 1, 2):
            self.material[strs[k]] = strs[k + 1]

    # ------------------------------------------------------------------
    def face_normals(self):
        p = self.pos
        t = self.tris
        n = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
        ln = np.linalg.norm(n, axis=1)
        return n / np.maximum(ln, 1e-12)[:, None], ln * 0.5

    def write_obj(self, path, groups=None, name='mesh', mtl=None, flip_v=True, winding_flip=False):
        """groups: optional list of (group name, triangle mask). OBJ vt uses v' = 1 - v (OBJ has v up)."""
        with open(path, 'w') as f:
            f.write('# Skate 3 %s  (%d verts, %d tris)  units: metres, Y up, model space\n' % (
                self.asset_name, self.nverts, len(self.tris)))
            if mtl:
                f.write('mtllib %s\n' % mtl)
            for p in self.pos:
                f.write('v %.6f %.6f %.6f\n' % tuple(p))
            for uv in self.uv:
                f.write('vt %.6f %.6f\n' % (uv[0], 1.0 - uv[1] if flip_v else uv[1]))
            if self.normal is not None:
                for n in self.normal:
                    f.write('vn %.5f %.5f %.5f\n' % tuple(n))
            if groups is None:
                groups = [(name, np.ones(len(self.tris), bool))]
            for gname, mask in groups:
                f.write('o %s\ng %s\n' % (gname, gname))
                if mtl:
                    f.write('usemtl %s\n' % gname)
                for tri in self.tris[mask]:
                    a, b, c = (int(x) + 1 for x in tri)
                    if winding_flip:
                        b, c = c, b
                    if self.normal is not None:
                        f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (a, a, a, b, b, b, c, c, c))
                    else:
                        f.write('f %d/%d %d/%d %d/%d\n' % (a, a, b, b, c, c))


if __name__ == '__main__':
    import sys
    np.set_printoptions(precision=5, suppress=True)
    for p in sys.argv[1:]:
        m = PsgModel(p)
        print(p.replace('\\', '/').split('/')[-1], m.asset_name)
        print('  elements (type,count,offset,stride,attr,1):', m.elements)
        print('  verts %d  tris %d  index max %d' % (m.nverts, len(m.tris), m.indices.max()))
        print('  stored bbox  min %s max %s' % (m.bbox[0], m.bbox[1]))
        print('  decoded bbox min %s max %s' % (m.pos.min(0), m.pos.max(0)))
        print('  uv0 min %s max %s' % (m.uv.min(0), m.uv.max(0)))
        for k, v in m.uv_sets.items():
            if k:
                print('  uv%d min %s max %s' % (k, v.min(0), v.max(0)))
        print('  palette:', [m.bones[i]['name'] for i in m.palette])
        print('  bones:', [(b['name'], np.round(b['pos'], 4).tolist()) for b in m.bones], 'counts', m.skel_counts, 'ids', m.skel_ids)
        if m.bone_idx is not None:
            u, c = np.unique(m.bone_idx, axis=0, return_counts=True)
            print('  blend indices used:', [(x.tolist(), int(n)) for x, n in zip(u, c)])
            u, c = np.unique(m.bone_wgt, axis=0, return_counts=True)
            print('  blend weights used:', [(x.tolist(), int(n)) for x, n in zip(u, c)][:8])
        print('  material:', m.material)
