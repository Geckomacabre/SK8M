"""RenderWare 4 "arena" (.psg, PS3, big-endian) container reader for Skate 3.

Only what was proven on the real files is implemented (see NOTES.md):
  header  0x00  magic  89 'RW4ps3' 00 0D 0A 1A 0A
          0x0C  u8 bigEndian, u8 pointerBits, u8 pointerAlign, u8 pad
          0x10  char[4] major ("454"), char[4] minor ("000"), u32 build
          0x1C  u32 arena id
          0x20  u32 numEntries, u32 numUsed, u32 alignment, u32 virt
          0x30  u32 dictStart, u32 sections, u32 base, u32 unfix, u32 fix
          0x44  resource descriptor: 6 x (u32 size, u32 align)   [0] = main memory, [5] = graphics (vertex / index) memory
          0x74  resources used:      6 x (u32 size, u32 align)
  dict    numEntries x { u32 ptr, u32 reloc, u32 size, u32 align, u32 typeIndex, u32 typeId }
          ptr is a file offset for main-memory objects; for BaseResource objects (typeId 0x0001003x) it is an offset
          inside the graphics block, which is the last descriptor[5].size bytes of the file (no alignment padding).
  sections (at header.sections): manifest 0x00010004 -> types 0x00010005, external arenas 0x00010006,
          subreferences 0x00010007, atoms 0x00010008

usage: python rw4_arena.py <file.psg> [...]     prints the dictionary
"""
import struct
import sys

MAGIC = b'\x89RW4ps3\x00\r\n\x1a\n'

TYPE_NAMES = {
    0x00010030: 'BaseResource0', 0x00010031: 'BaseResource1', 0x00010032: 'BaseResource2',
    0x00010033: 'BaseResource3', 0x00010034: 'BaseResource4', 0x00010010: 'Raw/Buffer',
    0x000200e8: 'PS3 0x200e8', 0x000200e9: 'VertexDescriptor(PS3)', 0x000200ea: 'VertexBuffer(PS3)',
    0x000200eb: 'IndexBuffer(PS3)', 0x00020081: '0x20081',
}


class Arena:
    def __init__(self, data):
        self.data = data
        if data[:12] != MAGIC:
            raise ValueError('not an RW4 ps3 arena')
        self.big, self.ptr_bits, self.ptr_align = data[12], data[13], data[14]
        self.version = data[16:20].rstrip(b'\0').decode(), data[20:24].rstrip(b'\0').decode()
        (self.id, self.num_entries, self.num_used, self.alignment, self.virt, self.dict_start, self.sections,
         self.base, self.unfix, self.fix) = struct.unpack_from('>10I', data, 0x1C)
        self.res_desc = [struct.unpack_from('>2I', data, 0x44 + 8 * i) for i in range(6)]
        self.res_used = [struct.unpack_from('>2I', data, 0x74 + 8 * i) for i in range(6)]
        # the graphics block (descriptor [5]) is the last desc[5].size bytes of the file: file size = desc[0].size +
        # desc[5].size on every file looked at (it is not padded up to its alignment)
        self.gfx_start = len(data) - self.res_desc[5][0]
        self.entries = []
        for i in range(self.num_entries):
            ptr, reloc, size, align, tidx, tid = struct.unpack_from('>6I', data, self.dict_start + 24 * i)
            self.entries.append(dict(i=i, ptr=ptr, reloc=reloc, size=size, align=align, tidx=tidx, type=tid))
        self._sections()

    def _sections(self):
        d, s = self.data, self.sections
        tid, n, off = struct.unpack_from('>3I', d, s)
        assert tid == 0x00010004, hex(tid)
        self.section_offs = [s + o for o in struct.unpack_from('>%dI' % n, d, s + off)]
        self.types = []
        self.subrefs = []
        for so in self.section_offs:
            stid = struct.unpack_from('>I', d, so)[0]
            if stid == 0x00010005:
                n, off = struct.unpack_from('>2I', d, so + 4)
                self.types = list(struct.unpack_from('>%dI' % n, d, so + off))
            elif stid == 0x00010007:
                # subreferences: u32 numEntries, then (dict, records) pointers; layout proven below in dump()
                self.subref_hdr = struct.unpack_from('>7I', d, so)

    def offset(self, e):
        """file offset of a dictionary entry's data (BaseResource entries live in the graphics block)"""
        if 0x00010030 <= e['type'] <= 0x0001003f:
            return self.gfx_start + e['ptr']
        return e['ptr']

    def blob(self, e):
        o = self.offset(e)
        return self.data[o:o + e['size']]

    def by_type(self, tid):
        return [e for e in self.entries if e['type'] == tid]


def dump(path):
    data = open(path, 'rb').read()
    a = Arena(data)
    print('%s  size %d  ver %s.%s  id %08x  entries %d  dict @%#x  sections @%#x' % (
        path.replace('\\', '/').split('/')[-1], len(data), a.version[0], a.version[1], a.id, a.num_entries,
        a.dict_start, a.sections))
    print('  resources:', ' '.join('(%#x,%d)' % r for r in a.res_desc), ' graphics block starts at %#x' % a.gfx_start)
    for e in a.entries:
        print('  [%2d] %-22s type %08x  off %#7x  size %#6x  align %2d  reloc %#x tidx %d' % (
            e['i'], TYPE_NAMES.get(e['type'], ''), e['type'], a.offset(e), e['size'], e['align'], e['reloc'], e['tidx']))
    return a


if __name__ == '__main__':
    for p in sys.argv[1:]:
        dump(p)
        print()
