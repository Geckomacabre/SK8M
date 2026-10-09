#!/usr/bin/env python3
"""
vlt_parse.py - parser for EA "AttribSys" vault databases as shipped in Skate 3 (PS3).

Format facts (all checked by --selftest against the real files):
  * big-endian, 32-bit pointers, 64-bit keys
  * keys = Bob Jenkins lookup8 ("hash64") with initial value 0xABCDEF0011223344
    over the lower-case ASCII name (class names, collection names, type names,
    file names, "class/collection" export ids and attribute names)
  * <name>.vlt : chunks  Vers, StrN, DepN, DatN, ExpN, PtrN, EndC
                 (4-char id, u32 size including the 8-byte header)
  * <name>.bin : chunk StrE (string pool), chunk EndC, then raw data to EOF

Usage:
  python vlt_parse.py --selftest
  python vlt_parse.py --dump  ~\\skate3-extract\\vlt\\dump
  python vlt_parse.py --show physics_push
Standard library only.
"""
import argparse
import collections
import glob
import json
import math
import os
import struct
import sys

import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "."))
import paths  # noqa: E402
DEFAULT_DB_DIR = paths.work(r"db\data\db")
HERE = os.path.dirname(os.path.abspath(__file__))

HASH_SEED = 0xABCDEF0011223344
M64 = 0xFFFFFFFFFFFFFFFF

DUMP_PREFIXES = ("physics", "camera", "anim", "scoring", "recognizer", "inputlistener",
                 "six_axis", "rumble", "skater", "state_controller", "slowmotion",
                 "ballspring", "drivetest")


# --------------------------------------------------------------------------- hash
def _mix64(a, b, c):
    a = (a - b - c) & M64; a ^= (c >> 43)
    b = (b - c - a) & M64; b ^= (a << 9) & M64
    c = (c - a - b) & M64; c ^= (b >> 8)
    a = (a - b - c) & M64; a ^= (c >> 38)
    b = (b - c - a) & M64; b ^= (a << 23) & M64
    c = (c - a - b) & M64; c ^= (b >> 5)
    a = (a - b - c) & M64; a ^= (c >> 35)
    b = (b - c - a) & M64; b ^= (a << 49) & M64
    c = (c - a - b) & M64; c ^= (b >> 11)
    a = (a - b - c) & M64; a ^= (c >> 12)
    b = (b - c - a) & M64; b ^= (a << 18) & M64
    c = (c - a - b) & M64; c ^= (b >> 22)
    return a, b, c


def hash64(s, seed=HASH_SEED):
    """Bob Jenkins lookup8 hash() (64-bit), as used for every AttribSys key in Skate 3."""
    k = s.encode("latin-1") if isinstance(s, str) else bytes(s)
    length = len(k)
    a = b = seed
    c = 0x9E3779B97F4A7C13
    o = 0
    n = length
    while n >= 24:
        a = (a + int.from_bytes(k[o:o + 8], "little")) & M64
        b = (b + int.from_bytes(k[o + 8:o + 16], "little")) & M64
        c = (c + int.from_bytes(k[o + 16:o + 24], "little")) & M64
        a, b, c = _mix64(a, b, c)
        o += 24
        n -= 24
    c = (c + length) & M64
    t = k[o:]
    if n > 16:
        c = (c + (int.from_bytes(t[16:], "little") << 8)) & M64   # low byte of c holds the length
    if n > 8:
        b = (b + int.from_bytes(t[8:16], "little")) & M64
    if n > 0:
        a = (a + int.from_bytes(t[0:8], "little")) & M64
    a, b, c = _mix64(a, b, c)
    return c


def hx(k):
    return "0x%016x" % k


# --------------------------------------------------------------------------- vault file pair
PTR_END, PTR_NULL, PTR_SET_TARGET, PTR_DEP_RELATIVE, PTR_EXPORT = 0, 1, 2, 3, 4

Export = collections.namedtuple("Export", "key type size offset")


class Vault:
    """One <name>.vlt / <name>.bin pair."""

    def __init__(self, vlt_path, bin_path=None):
        self.vlt_path = vlt_path
        self.bin_path = bin_path or (os.path.splitext(vlt_path)[0] + ".bin")
        self.name = os.path.splitext(os.path.basename(vlt_path))[0]
        with open(self.vlt_path, "rb") as f:
            self.vlt = f.read()
        with open(self.bin_path, "rb") as f:
            self.bin = f.read()
        self.problems = []
        self._chunks()
        self._deps()
        self._exports()
        self._pointers()

    # -- chunk walk
    @staticmethod
    def walk_chunks(buf):
        out = []
        o = 0
        while o + 8 <= len(buf):
            cid = buf[o:o + 4]
            size = struct.unpack_from(">I", buf, o + 4)[0]
            if size < 8 or o + size > len(buf):
                out.append((cid.decode("latin-1"), o, size))
                return out, None
            out.append((cid.decode("latin-1"), o, size))
            o += size
            if cid == b"EndC":
                break
        return out, o

    def _chunks(self):
        self.vlt_chunks, vend = self.walk_chunks(self.vlt)
        self.bin_chunks, bend = self.walk_chunks(self.bin)
        self.chunk = {c[0]: (c[1], c[2]) for c in self.vlt_chunks}
        if vend != len(self.vlt):
            self.problems.append("vlt chunks do not tile the file")
        if [c[0] for c in self.vlt_chunks] != ["Vers", "StrN", "DepN", "DatN", "ExpN", "PtrN", "EndC"]:
            self.problems.append("unexpected vlt chunk order %r" % [c[0] for c in self.vlt_chunks])
        if [c[0] for c in self.bin_chunks] != ["StrE", "EndC"] or bend is None:
            self.problems.append("unexpected bin chunk order %r" % [c[0] for c in self.bin_chunks])
            bend = 0
        self.version = struct.unpack_from(">Q", self.vlt, self.chunk["Vers"][0] + 8)[0] if "Vers" in self.chunk else None
        # bin regions (absolute file offsets)
        self.stre = (8, self.bin_chunks[0][1] + self.bin_chunks[0][2]) if self.bin_chunks else (0, 0)
        self.bin_data_start = bend
        self.datn = (self.chunk["DatN"][0] + 8, self.chunk["DatN"][0] + self.chunk["DatN"][1])

    def _deps(self):
        o, size = self.chunk["DepN"]
        n = struct.unpack_from(">Q", self.vlt, o + 8)[0]
        hashes = struct.unpack_from(">%dQ" % n, self.vlt, o + 16)
        offs = struct.unpack_from(">%dI" % n, self.vlt, o + 16 + 8 * n)
        base = o + 16 + 12 * n
        self.deps = []
        for h, no in zip(hashes, offs):
            end = self.vlt.index(b"\0", base + no)
            self.deps.append((h, self.vlt[base + no:end].decode("latin-1")))

    def _exports(self):
        o, size = self.chunk["ExpN"]
        n = struct.unpack_from(">Q", self.vlt, o + 8)[0]
        if not (0 <= size - (16 + 24 * n) < 16):      # chunk sizes are padded to 16 bytes
            self.problems.append("ExpN size %d != 16 + 24*%d (+pad)" % (size, n))
        self.exports = [Export(*struct.unpack_from(">QQII", self.vlt, o + 16 + 24 * i)) for i in range(n)]

    def _pointers(self):
        """PtrN: array of PtrRef {u32 fixupOffset; u16 ptrType; u16 index; u64 offset}."""
        o, size = self.chunk["PtrN"]
        n = (size - 8) // 16
        self.fix = {0: {}, 1: {}}          # dep index -> {fixup file offset: (target dep, target offset)}
        self.ptr_counts = collections.Counter()
        cur = None
        ended = False
        for i in range(n):
            foff, ptype, index, dest = struct.unpack_from(">IHHQ", self.vlt, o + 8 + 16 * i)
            self.ptr_counts[ptype] += 1
            if ptype == PTR_END:
                ended = True
                if i != n - 1:
                    self.problems.append("PtrN end marker is not the last entry")
                break
            if ptype == PTR_SET_TARGET:
                cur = index
            elif ptype == PTR_DEP_RELATIVE:
                if cur not in self.fix:
                    self.problems.append("pointer fixup before any set-target entry")
                    continue
                self.fix[cur][foff] = (index, dest)
            else:
                self.problems.append("unhandled PtrRef type %d" % ptype)
        if not ended:
            self.problems.append("PtrN has no end marker")

    # -- helpers
    def cstr(self, off):
        """C string at absolute .bin offset."""
        end = self.bin.find(b"\0", off)
        if end < 0:
            end = len(self.bin)
        return self.bin[off:end]

    def buf(self, dep):
        return self.vlt if dep == 0 else self.bin


# --------------------------------------------------------------------------- schema
class TypeInfo:
    __slots__ = ("index", "name", "size", "key")

    def __init__(self, index, name, size):
        self.index, self.name, self.size, self.key = index, name, size, hash64(name)

    def __repr__(self):
        return "<Type %s %d>" % (self.name, self.size)


DEF_ARRAY, DEF_IN_LAYOUT, DEF_BOUND, DEF_UNK08, DEF_STATIC, DEF_HAS_REFSPEC = 1, 2, 4, 8, 0x10, 0x20


class AttrDef:
    """Attrib::Definition, 24 bytes: u64 key; u64 type; u16 offset; u16 size; u16 maxCount; u8 flags; u8 alignment."""
    __slots__ = ("key", "type_key", "type", "offset", "size", "max_count", "flags", "alignment", "name")

    @property
    def is_array(self):
        return bool(self.flags & DEF_ARRAY)

    @property
    def in_layout(self):
        return bool(self.flags & DEF_IN_LAYOUT)

    @property
    def is_static(self):
        return bool(self.flags & DEF_STATIC)

    @property
    def label(self):
        return self.name if self.name else hx(self.key)

    def layout_span(self):
        """bytes this attribute occupies inside the class layout struct."""
        if not self.is_array:
            return self.size
        return (16 if self.alignment >= 4 else 8) + self.max_count * self.size


class ClassDef:
    """Attrib::ClassLoadData, 40 bytes (see REPORT.md)."""

    def __init__(self):
        self.key = 0
        self.name = None
        self.collection_reserve = 0
        self.num_definitions = 0
        self.definitions_ptr = None
        self.static_size = 0
        self.static_ptr = None
        self.layout_size = 0
        self.unk20 = 0
        self.unk22 = 0
        self.unk24 = 0
        self.defs = []
        self.by_key = {}
        self.offset = 0


NODE_ARRAY, NODE_HAS_REFSPEC, NODE_INLINE = 0x02, 0x08, 0x40


class Entry:
    """CollectionLoadData::AttribEntry, 16 bytes: u64 key; u32 data; u16 typeIndex; u8 nodeFlags; u8 entryFlags."""
    __slots__ = ("key", "data_off", "type_index", "node_flags", "entry_flags", "ptr")


class Collection:
    def __init__(self):
        self.vault = None
        self.export_key = 0
        self.offset = 0
        self.size = 0
        self.key = 0
        self.class_key = 0
        self.parent_key = 0
        self.table_reserve = 0
        self.key_shift = 0
        self.num_entries = 0
        self.num_types = 0
        self.types_len = 0
        self.layout_ptr = None      # absolute .bin offset or None
        self.type_keys = []
        self.entries = []
        self.by_key = {}
        self.name = None            # from the summary report


# Attrib::Array header is 8 bytes {u16 mAlloc; u16 mCount; u16 mSize; u16 mEncodedTypeAndPad}.
# mEncodedTypeAndPad is 0x8000 exactly when the element type is 16-byte aligned (definition
# alignment == 4, i.e. log2(16)); the elements then start 16 bytes after the header start instead of 8.


# --------------------------------------------------------------------------- value decoding
def _f(x):
    """float32 -> JSON-safe python float (rounded to float32 shortest repr)."""
    if x != x or x in (float("inf"), float("-inf")):
        return repr(x)
    return float("%.9g" % x) if x != 0 else 0.0


def f32_short(x):
    """shortest decimal that round-trips a float32."""
    if x != x or x in (float("inf"), float("-inf")):
        return repr(x)
    for prec in range(1, 10):
        s = "%.*g" % (prec, x)
        if struct.unpack(">f", struct.pack(">f", float(s)))[0] == x:
            return float(s)
    return float(x)


def float_plausible(x):
    """True for 0 and for normal floats of sane magnitude (rejects NaN/Inf/denormals/garbage)."""
    if x == 0:
        return True
    if x != x or x in (float("inf"), float("-inf")):
        return False
    return 1e-12 <= abs(x) <= 1e12


def word_guess(w):
    """Classify a raw u32 of unknown meaning: returns ('f', float) or ('i', int)."""
    if w == 0:
        return ("i", 0)
    exp = (w >> 23) & 0xFF
    if 0x60 <= exp <= 0x9F:              # |x| in ~[2^-31, 2^33): looks like a float
        return ("f", f32_short(struct.unpack(">f", struct.pack(">I", w))[0]))
    if w >= 0x80000000:
        return ("i", w - (1 << 32) if w >= 0xFFFF0000 else w)
    return ("i", w)


class Database:
    def __init__(self, db_dir=DEFAULT_DB_DIR, schema="skaterschema", collections_name="skatercollections",
                 names_path=None):
        self.db_dir = db_dir
        self.schema_vault = Vault(os.path.join(db_dir, schema + ".vlt"))
        self.coll_vault = Vault(os.path.join(db_dir, collections_name + ".vlt"))
        self.report_path = os.path.join(db_dir, collections_name + "_summaryreport.txt")
        self.names = {}             # hash -> string (anything we can name)
        self.attr_names = {}        # hash -> attribute name (proven by hash match)
        self.problems = []
        self._load_report_names()
        self._load_schema()
        self._load_collections()
        self._name_collections()
        self.load_attr_names(names_path or os.path.join(HERE, "names.json"))

    # -- names -------------------------------------------------------------
    def _load_report_names(self):
        """Class and collection names in clear text from every *_summaryreport.txt under db_dir."""
        self.report = []            # (class name, collection path) for the main report
        self.all_report_classes = set()
        for path in sorted(glob.glob(os.path.join(self.db_dir, "**", "*_summaryreport.txt"), recursive=True)):
            main = os.path.normcase(path) == os.path.normcase(self.report_path)
            with open(path, encoding="latin-1") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.strip("/").split("/")
                    cls = parts[0][:-6] if parts[0].endswith(".class") else parts[0]
                    rest = "/".join(parts[1:])
                    if rest.endswith(".xml"):
                        rest = rest[:-4]
                    self.all_report_classes.add(cls)
                    if main:
                        self.report.append((cls, rest))
        for c in self.all_report_classes:
            self.names[hash64(c)] = c

    def load_attr_names(self, path):
        self.attr_names = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                j = json.load(f)
            for name, info in j.get("attributes", {}).items():
                if hash64(name) == int(info["hash"], 16):       # only accept proven names
                    self.attr_names[hash64(name)] = name
        for cls in self.classes.values():
            for d in cls.defs:
                d.name = self.attr_names.get(d.key)

    # -- schema ------------------------------------------------------------
    def _load_schema(self):
        v = self.schema_vault
        self.types = []
        self.type_by_key = {}
        self.classes = {}
        self.class_by_name = {}
        self.db_export = None
        k_db = hash64("Attrib::DatabaseLoadData")
        k_cls = hash64("Attrib::ClassLoadData")
        self.EXPORT_TYPES = {k_db: "Attrib::DatabaseLoadData", k_cls: "Attrib::ClassLoadData",
                             hash64("Attrib::CollectionLoadData"): "Attrib::CollectionLoadData"}
        for e in v.exports:
            if e.type == k_db:
                self.db_export = e
        e = self.db_export
        # DatabaseLoadData {u32 mNumClasses; u32 mDefaultDataSize; u32 mNumTypes; ptr mTypenames; u32 typeSizes[mNumTypes]}
        self.db_num_classes, self.db_default_data_size, ntypes, _ = struct.unpack_from(">IIII", v.vlt, e.offset)
        tn = v.fix[0][e.offset + 12]
        self.typenames_ptr = tn[1]
        sizes = struct.unpack_from(">%dI" % ntypes, v.vlt, e.offset + 16)
        o = tn[1]
        for i in range(ntypes):
            s = v.cstr(o)
            t = TypeInfo(i, s.decode("latin-1"), sizes[i])
            self.types.append(t)
            self.type_by_key[t.key] = t
            self.names[t.key] = t.name
            o += len(s) + 1
        self.typenames_end = o
        # class names that only appear as Attrib::Gen::ClassRefSpec_<class> type names
        for t in self.types:
            if t.name.startswith("Attrib::Gen::ClassRefSpec_"):
                c = t.name[len("Attrib::Gen::ClassRefSpec_"):]
                self.names.setdefault(hash64(c), c)
        for e in v.exports:
            if e.type != k_cls:
                continue
            c = ClassDef()
            (c.key, c.collection_reserve, c.num_definitions, _p1, c.static_size, _p2, c.layout_size,
             c.unk20, c.unk22, c.unk24) = struct.unpack_from(">QIIIIIIHHI", v.vlt, e.offset)
            c.offset = e.offset
            c.name = self.names.get(c.key)
            p = v.fix[0].get(e.offset + 0x10)
            c.definitions_ptr = p[1] if p else None
            p = v.fix[0].get(e.offset + 0x18)
            c.static_ptr = p[1] if p else None
            if c.definitions_ptr is not None:
                for i in range(c.num_definitions):
                    d = AttrDef()
                    (d.key, d.type_key, d.offset, d.size, d.max_count, d.flags, d.alignment) = struct.unpack_from(
                        ">QQHHHBB", v.bin, c.definitions_ptr + 24 * i)
                    d.type = self.type_by_key.get(d.type_key)
                    d.name = None
                    c.defs.append(d)
                    c.by_key[d.key] = d
            self.classes[c.key] = c
            if c.name:
                self.class_by_name[c.name] = c

    # -- collections -------------------------------------------------------
    def _load_collections(self):
        v = self.coll_vault
        self.collections = {}            # (class key, collection key) -> Collection
        self.by_class = collections.defaultdict(list)
        self.by_export = {}
        k_col = hash64("Attrib::CollectionLoadData")
        for e in v.exports:
            if e.type != k_col:
                continue
            c = Collection()
            c.vault = v
            c.export_key, c.offset, c.size = e.key, e.offset, e.size
            (c.key, c.class_key, c.parent_key, c.table_reserve, c.key_shift, c.num_entries, c.num_types,
             c.types_len, _lay, c.pad2c) = struct.unpack_from(">QQQIIIHHII", v.vlt, e.offset)
            p = v.fix[0].get(e.offset + 0x28)
            c.layout_ptr = p[1] if p else None
            c.type_keys = list(struct.unpack_from(">%dQ" % c.types_len, v.vlt, e.offset + 0x30))
            eo = e.offset + 0x30 + 8 * c.types_len
            for i in range(c.num_entries):
                en = Entry()
                en.key, _data, en.type_index, en.node_flags, en.entry_flags = struct.unpack_from(">QIHBB", v.vlt, eo + 16 * i)
                en.data_off = eo + 16 * i + 8
                p = v.fix[0].get(en.data_off)
                en.ptr = p[1] if p else None
                c.entries.append(en)
                c.by_key[en.key] = en
            self.collections[(c.class_key, c.key)] = c
            self.by_class[c.class_key].append(c)
            self.by_export[c.export_key] = c

    def _name_collections(self):
        """Attach clear-text names from the summary report. Export id = hash64("<class>/<collection>")."""
        self.report_found = []
        self.report_missing = []
        for cls, rest in self.report:
            c = self.by_export.get(hash64(cls + "/" + rest))
            if c is None:
                self.report_missing.append((cls, rest))
                continue
            c.name = rest
            self.names[c.key] = rest.split("/")[-1] if hash64(rest) != c.key else rest
            self.report_found.append((cls, rest, c))
        # collection-name pool for resolving RefSpecs that point at collections we do not hold
        for cls, rest in self.report:
            self.names.setdefault(hash64(rest), rest)
            self.names.setdefault(hash64(rest.split("/")[-1]), rest.split("/")[-1])

    # -- lookup helpers ----------------------------------------------------
    def cls(self, name):
        return self.class_by_name[name]

    def coll_name(self, class_key, coll_key):
        c = self.collections.get((class_key, coll_key))
        if c is not None and c.name:
            return c.name
        return self.names.get(coll_key)

    def parent_of(self, c):
        if not c.parent_key:
            return None
        return self.collections.get((c.class_key, c.parent_key))

    # -- decoding ----------------------------------------------------------
    def text_at(self, vault, dep, off):
        """EA::Reflection::Text: a 32-bit pointer (fixed up through PtrN) to a C string."""
        p = vault.fix[dep].get(off)
        if p is None:
            raw = struct.unpack_from(">I", vault.buf(dep), off)[0]
            return None if raw == 0 else {"unfixed_pointer": raw}
        return vault.cstr(p[1]).decode("latin-1")

    def refspec(self, class_key, coll_key):
        out = {"class": self.names.get(class_key, hx(class_key)) if class_key else None,
               "collection": None}
        if coll_key:
            out["collection"] = self.coll_name(class_key, coll_key) or hx(coll_key)
        return out

    def decode(self, vault, dep, off, t):
        """Decode one value of TypeInfo t at file offset off of dependency dep (0 = .vlt, 1 = .bin)."""
        b = vault.buf(dep)
        n = t.name
        U = struct.unpack_from
        if n == "EA::Reflection::Float":
            return f32_short(U(">f", b, off)[0])
        if n == "EA::Reflection::Bool":
            return bool(b[off]) if b[off] in (0, 1) else {"bad_bool": b[off]}
        if n == "EA::Reflection::Int32":
            return U(">i", b, off)[0]
        if n == "EA::Reflection::UInt32":
            return U(">I", b, off)[0]
        if n == "EA::Reflection::Int16":
            return U(">h", b, off)[0]
        if n == "EA::Reflection::UInt16":
            return U(">H", b, off)[0]
        if n == "EA::Reflection::Int8":
            return U(">b", b, off)[0]
        if n in ("EA::Reflection::UInt8", "EA::Reflection::Char"):
            return b[off]
        if n == "EA::Reflection::Int64":
            return U(">q", b, off)[0]
        if n == "EA::Reflection::UInt64":
            return hx(U(">Q", b, off)[0])
        if n == "EA::Reflection::Double":
            return U(">d", b, off)[0]
        if n == "EA::Reflection::Text":
            return self.text_at(vault, dep, off)
        if n == "Attrib::RefSpec":
            # {u64 classKey; u64 collectionKey; u32 runtime pointer; u32 pad}
            ck, ok = U(">QQ", b, off)
            return self.refspec(ck, ok)
        if n.startswith("Attrib::Gen::ClassRefSpec_"):
            # {u64 collectionKey; u32 runtime pointer; u32 pad}; the class is implied by the type name
            ok = U(">Q", b, off)[0]
            return self.refspec(hash64(n[len("Attrib::Gen::ClassRefSpec_"):]), ok)
        if n in ("Attrib::Types::Vector2",):
            return [f32_short(x) for x in U(">2f", b, off)]
        if n in ("Attrib::Types::Vector3",):
            return [f32_short(x) for x in U(">3f", b, off)]
        if n in ("Attrib::Types::Vector4", "Attrib::Types::Quaternion", "Attrib::Types::FloatColour",
                 "Attrib::Types::ShaderColour", "Math::Vector4", "Math::Vector3", "Math::Vector2"):
            return [f32_short(x) for x in U(">4f", b, off)]
        if n == "Attrib::Types::Matrix":
            return [[f32_short(x) for x in U(">4f", b, off + 16 * r)] for r in range(4)]
        if n in ("Attrib::Key", "Attrib::AttributeKey", "Attrib::CollectionKey", "Attrib::ClassKey", "Attrib::Type"):
            k = U(">Q", b, off)[0]
            return {"key": hx(k), "name": self.names.get(k) or self.attr_names.get(k)}
        if n in ("Attrib::Blob", "LuaState::tLuaBlob"):
            size = U(">I", b, off)[0]
            p = vault.fix[dep].get(off + 4)
            out = {"blob_size": size, "blob_offset": p[1] if p else None}
            if p and size:
                data = vault.bin[p[1]:p[1] + size]
                out["is_lua_bytecode"] = data[:4] == b"\x1bLua"
            return out
        g = GRAPH_TYPES.get(n)
        if g:
            return self.decode_graph(b, off, *g)
        if n in STRUCTS:
            return self.decode_struct(vault, dep, off, STRUCTS[n])
        return self.decode_unknown(vault, dep, off, t.size)

    @staticmethod
    def decode_graph(b, off, npts, neg):
        """Sk8::PointGraphData<N> = {float x[N]; float y[N]};
        Sk8::PointNegGraphData<N> = {float min_x, min_y, max_x, max_y; float x[N]; float y[N]}.
        Verified statistically in --selftest (every x inside [min_x, max_x], every y inside [min_y, max_y])."""
        o = off
        out = {}
        if neg:
            h = struct.unpack_from(">4f", b, o)
            o += 16
            out["min_x"], out["min_y"], out["max_x"], out["max_y"] = [f32_short(v) for v in h]
        out["x"] = [f32_short(v) for v in struct.unpack_from(">%df" % npts, b, o)]
        out["y"] = [f32_short(v) for v in struct.unpack_from(">%df" % npts, b, o + 4 * npts)]
        return out

    def decode_struct(self, vault, dep, off, fields):
        b = vault.buf(dep)
        out = {}
        for fname, fmt, foff in fields:
            if fmt == "f":
                out[fname] = f32_short(struct.unpack_from(">f", b, off + foff)[0])
            elif fmt == "i":
                out[fname] = struct.unpack_from(">i", b, off + foff)[0]
            elif fmt == "I":
                out[fname] = struct.unpack_from(">I", b, off + foff)[0]
            elif fmt == "B":
                out[fname] = b[off + foff]
            elif fmt == "s":
                out[fname] = self.text_at(vault, dep, off + foff)
            elif fmt == "k":
                k = struct.unpack_from(">Q", b, off + foff)[0]
                out[fname] = self.names.get(k, hx(k)) if k else None
        return out

    def decode_unknown(self, vault, dep, off, size):
        """Struct or enum whose member layout is not known: 4-byte words, each either a resolved
        pointer (string), a float-looking word or an integer.  Marked so nobody mistakes it for fact."""
        b = vault.buf(dep)
        fix = vault.fix[dep]
        if size == 4 and off not in fix:
            return struct.unpack_from(">i", b, off)[0]
        if size in (1, 2) and off not in fix:
            return int.from_bytes(b[off:off + size], "big")
        words = []
        i = 0
        while i + 4 <= size:
            if off + i in fix:
                tgt = fix[off + i][1]
                if vault.stre[0] <= tgt < vault.stre[1]:
                    words.append(vault.cstr(tgt).decode("latin-1"))
                else:
                    words.append({"ptr": tgt})
            else:
                words.append(word_guess(struct.unpack_from(">I", b, off + i)[0])[1])
            i += 4
        if i < size:
            words.append({"tail_bytes": b[off + i:off + size].hex()})
        return {"guessed_words": words}

    def read_array(self, vault, dep, off, d):
        """Attrib::Array {u16 mAlloc; u16 mCount; u16 mSize; u16 mEncodedTypeAndPad} + elements."""
        b = vault.buf(dep)
        alloc, count, esize, enc = struct.unpack_from(">HHHH", b, off)
        start = off + (16 if enc & 0x8000 else 8)
        return [self.decode(vault, dep, start + i * d.size, d.type) for i in range(count)], (alloc, count, esize, enc)

    def own_value(self, c, d):
        """Value of attribute d stored in collection c itself; returns (found, value, where)."""
        v = c.vault
        if d.in_layout:
            if c.layout_ptr is None:
                return False, None, None
            off = c.layout_ptr + d.offset
            if d.is_array:
                return True, self.read_array(v, 1, off, d)[0], "layout"
            return True, self.decode(v, 1, off, d.type), "layout"
        e = c.by_key.get(d.key)
        if e is None:
            return False, None, None
        if e.node_flags & NODE_ARRAY:
            return True, self.read_array(v, 1, e.ptr, d)[0], "entry"
        if e.node_flags & NODE_INLINE:
            return True, self.decode(v, 0, e.data_off, d.type), "entry"
        return True, self.decode(v, 1, e.ptr, d.type), "entry"

    def static_value(self, cls, d):
        if cls.static_ptr is None:
            return None
        return self.decode(self.schema_vault, 1, cls.static_ptr + d.offset, d.type)

    def resolve(self, c):
        """All attribute values of a collection with inheritance resolved.
        Returns {attr key: {"value", "source", "inherited", "from"}}."""
        cls = self.classes[c.class_key]
        out = {}
        chain = []
        p = c
        seen = set()
        while p is not None and id(p) not in seen:
            seen.add(id(p))
            chain.append(p)
            p = self.parent_of(p)
        for d in cls.defs:
            if d.is_static:
                out[d.key] = {"value": self.static_value(cls, d), "source": "class-static", "inherited": False}
                continue
            got = False
            for depth, anc in enumerate(chain):
                found, val, where = self.own_value(anc, d)
                if found:
                    rec = {"value": val, "source": where, "inherited": depth > 0}
                    if depth > 0:
                        rec["from"] = anc.name or hx(anc.key)
                    elif where == "layout" and len(chain) > 1:
                        # every collection carries a full copy of the layout struct, so an explicit
                        # override cannot be told apart from a copied parent value; report equality
                        pf, pv, _ = self.own_value(chain[1], d)
                        rec["same_as_parent"] = bool(pf and pv == val)
                    out[d.key] = rec
                    got = True
                    break
            if not got:
                out[d.key] = {"value": None, "source": "unset", "inherited": False}
        return out

    # -- JSON dump ---------------------------------------------------------
    def class_json(self, cls):
        defs = []
        for d in sorted(cls.defs, key=lambda d: (not d.in_layout, d.offset if d.in_layout else 0, d.key)):
            defs.append({
                "key": hx(d.key), "name": d.name, "type": d.type.name if d.type else hx(d.type_key),
                "size": d.size, "array_max": d.max_count, "offset": d.offset if d.in_layout else None,
                "flags": "0x%02x" % d.flags, "is_array": d.is_array, "in_layout": d.in_layout,
                "is_static": d.is_static, "alignment_log2": d.alignment,
            })
        colls = {}
        order = sorted(self.by_class.get(cls.key, []), key=lambda c: (c.name != "default", c.name or hx(c.key)))
        for c in order:
            res = self.resolve(c)
            vals = {}
            for d in sorted(cls.defs, key=lambda d: (not d.in_layout, d.offset if d.in_layout else 0, d.key)):
                r = dict(res[d.key])
                r["type"] = d.type.name
                vals[d.label] = r
            par = self.parent_of(c)
            colls[c.name or hx(c.key)] = {
                "key": hx(c.key),
                "parent": (par.name or hx(par.key)) if par else (hx(c.parent_key) if c.parent_key else None),
                "num_own_entries": c.num_entries, "has_layout": c.layout_ptr is not None,
                "values": vals,
            }
        named = sum(1 for d in cls.defs if d.name)
        return {
            "class": cls.name, "class_key": hx(cls.key), "layout_size": cls.layout_size,
            "num_definitions": cls.num_definitions, "num_names_recovered": named,
            "note": "name=null means the attribute name is NOT recovered (only its 64-bit hash is known). "
                    "Values under 'guessed_words' and graph 'points'/'tail' use an inferred struct layout.",
            "attributes": defs, "collections": colls,
        }

    def dump(self, out_dir, prefixes=DUMP_PREFIXES):
        os.makedirs(out_dir, exist_ok=True)
        n = 0
        for cls in sorted(self.classes.values(), key=lambda c: c.name or ""):
            if cls.name and cls.name.startswith(prefixes):
                with open(os.path.join(out_dir, cls.name + ".json"), "w", encoding="utf-8") as f:
                    json.dump(self.class_json(cls), f, indent=1)
                n += 1
        return n


# Struct member layouts. Entries here are INFERRED from the data unless a comment says otherwise.
GRAPH_TYPES = {
    "Sk8::PointGraphData4": (4, False), "Sk8::PointGraphData8": (8, False), "Sk8::PointGraphData16": (16, False),
    "Sk8::PointNegGraphData4": (4, True), "Sk8::PointNegGraphData8": (8, True), "Sk8::PointNegGraphData16": (16, True),
}
STRUCTS = {
    # member names as published in Skate-Modding-Team/VaultTest DatabaseTypes.h (sizes agree with the type table)
    "Sk8::Input::tRumbleInfo": [("HighFreq", "f", 0), ("LowFreq", "f", 4), ("Decay", "f", 8)],
    "Sk8::AI::ProfileTrickEntry": [("ID", "i", 0), ("Weight", "f", 4)],
    "Sk8::FE::tTrickGuideInputSlot": [("Gesture", "i", 0), ("Button", "i", 4), ("Connector", "i", 8)],
    "Sk8::Physics::PhysicsControllerData": [("mPVal", "f", 0), ("mIVal", "f", 4), ("mDVal", "f", 8), ("unnamed_0x0C", "f", 12)],
    "LuaState::tCompiledLua": [("SourceLua", "s", 0), ("CompiledLua.Size", "I", 4), ("CompiledLua.Data", "s", 8)],
}


# --------------------------------------------------------------------------- self test
class Check:
    def __init__(self, title):
        self.title = title
        self.ok = 0
        self.bad = 0
        self.examples = []
        self.note = ""
        self.info = False

    def add(self, cond, example=None):
        if cond:
            self.ok += 1
        else:
            self.bad += 1
            if example is not None and len(self.examples) < 6:
                self.examples.append(example)
        return cond

    def line(self):
        tag = "PASS" if self.bad == 0 else ("INFO" if self.info else "FAIL")
        s = "[%s] %-58s %s %6d  %s %5d" % (tag, self.title, "yes " if self.info else "pass", self.ok,
                                             "no  " if self.info else "fail", self.bad)
        if self.note:
            s += "\n         note: " + self.note
        for e in self.examples:
            s += "\n         e.g. " + str(e)
        return s


def printable(s):
    return all(32 <= ord(ch) < 127 or ch in "\t\n\r" or 160 <= ord(ch) < 256 for ch in s)


def selftest(db, verbose=True):
    checks = []

    def new(title):
        c = Check(title)
        checks.append(c)
        return c

    vaults = [db.schema_vault, db.coll_vault]

    # 1 container
    c = new("container: chunk order/sizes tile both files")
    for v in vaults:
        c.add(not v.problems, (v.name, v.problems))
        c.add(v.vlt_chunks[-1][1] + v.vlt_chunks[-1][2] == len(v.vlt), v.name)
        c.add(v.bin_data_start <= len(v.bin), v.name)

    c = new("hash: DepN file-name hashes == hash64(file name)")
    for v in vaults:
        for h, nm in v.deps:
            c.add(hash64(nm) == h, (nm, hx(h)))

    c = new("hash: export type ids are Attrib::*LoadData")
    for v in vaults:
        for e in v.exports:
            c.add(e.type in db.EXPORT_TYPES, hx(e.type))
    c2 = new("hash: database export id == hash64('Attrib::Database')")
    c2.add(db.db_export.key == hash64("Attrib::Database"))

    c = new("exports tile the DatN chunk (gaps < 8 bytes, all zero)")
    for v in vaults:
        pos = v.datn[0]
        for e in sorted(v.exports, key=lambda e: e.offset):
            gap = e.offset - pos
            c.add(0 <= gap < 8 and not any(v.vlt[pos:e.offset]), (v.name, hex(pos), hex(e.offset)))
            pos = e.offset + e.size
        gap = v.datn[1] - pos
        c.add(0 <= gap < 16 and not any(v.vlt[pos:v.datn[1]]), (v.name, "tail", hex(pos), hex(v.datn[1])))

    # 2 pointers
    c = new("pointers: fixup location inside DatN / .bin data")
    ct = new("pointers: target inside the .bin (StrE or data region)")
    for v in vaults:
        for dep in (0, 1):
            for foff, (tdep, tgt) in v.fix[dep].items():
                if dep == 0:
                    c.add(v.datn[0] <= foff <= v.datn[1] - 4, (v.name, "vlt", hex(foff)))
                else:
                    c.add(v.bin_data_start <= foff <= len(v.bin) - 4, (v.name, "bin", hex(foff)))
                ok = tdep == 1 and (v.stre[0] <= tgt < v.stre[1] or v.bin_data_start <= tgt < len(v.bin))
                ct.add(ok, (v.name, dep, hex(foff), tdep, hex(tgt)))
    c = new("pointers: slot being fixed up holds 0 on disk")
    for v in vaults:
        for dep in (0, 1):
            b = v.buf(dep)
            for foff in v.fix[dep]:
                c.add(b[foff:foff + 4] == b"\0\0\0\0", (v.name, dep, hex(foff)))

    # 3 names
    rep_classes = sorted({cls for cls, _ in db.report})
    c = new("names: summary-report class name hashes to a schema class")
    for cls in rep_classes:
        c.add(hash64(cls) in db.classes, cls)
    miss_cls = sorted(cls for cls in rep_classes if hash64(cls) not in db.classes)
    if miss_cls:
        c.note = ("%d report classes have no ClassLoadData in skaterschema.vlt (all 'worldpainter_dist_*': %s)"
                  % (len(miss_cls), all(m.startswith("worldpainter_dist_") for m in miss_cls)))
    c = new("names: every schema class has a clear-text name")
    for cls in db.classes.values():
        c.add(cls.name is not None, hx(cls.key))
    c = new("names: report /class/collection found as export")
    for cls, rest in db.report:
        c.add(hash64(cls + "/" + rest) in db.by_export, cls + "/" + rest)
    if db.report_missing:
        cnt = collections.Counter(cls if not cls.startswith("worldpainter_dist_") else "worldpainter_dist_*"
                                  for cls, _ in db.report_missing)
        c.note = "missing by class: %s" % dict(cnt)
    c = new("names: every collection export is named by the report")
    for col in db.collections.values():
        c.add(col.name is not None, hx(col.export_key))
    c = new("names: collection key == hash64(last path element or path)")
    cc = new("names: collection class key == hash64(class name)")
    for cls, rest, col in db.report_found:
        c.add(col.key in (hash64(rest), hash64(rest.split("/")[-1])), (cls, rest))
        cc.add(col.class_key == hash64(cls), (cls, rest))

    # 4 schema
    c = new("schema: definition type hash is in the type table")
    cs = new("schema: definition size == type size")
    ca = new("schema: alignment is log2 and divides layout offset")
    co = new("schema: definitions sorted by key, unique")
    cl = new("schema: layout members inside layout, no overlap")
    cg = new("schema: layout fully covered (gaps = alignment only)")
    for cls in db.classes.values():
        prev = -1
        spans = []
        for d in cls.defs:
            if not c.add(d.type is not None, (cls.name, hx(d.key), hx(d.type_key))):
                continue
            cs.add(d.size == d.type.size, (cls.name, hx(d.key), d.size, d.type))
            co.add(d.key > prev, (cls.name, hx(d.key)))
            prev = d.key
            if d.in_layout:
                ca.add(d.alignment <= 4 and d.offset % (1 << d.alignment) == 0, (cls.name, hx(d.key), d.offset, d.alignment))
                spans.append((d.offset, d.offset + d.layout_span(), d))
            else:
                ca.add(d.alignment <= 4, (cls.name, hx(d.key)))
        spans.sort(key=lambda s: (s[0], s[1]))
        pos = 0
        good = True
        gaps_ok = True
        for a, b, d in spans:
            if a < pos or b > cls.layout_size:
                good = False
            if a - pos >= 16:
                gaps_ok = False
            pos = max(pos, b)
        if cls.layout_size - pos >= 16:
            gaps_ok = False
        cl.add(good, cls.name)
        cg.add(gaps_ok, (cls.name, cls.layout_size, pos))

    # 5 collections
    c_sz = new("collections: size == 0x30 + 8*typesLen + 16*numEntries")
    c_cls = new("collections: class key is a schema class")
    c_par = new("collections: parent key resolves in same class, no cycle")
    c_lay = new("collections: layout pointer present iff class has a layout")
    c_tl = new("collections: typesLen == numTypes rounded up to even")
    c_key = new("entries: key is an attribute of the class")
    c_typ = new("entries: type index valid and == definition type")
    c_fl = new("entries: node flags consistent with type/array/pointer")
    c_arr = new("arrays: header size/count/alloc/align flag consistent")
    c_nolay = new("entries: never duplicate an in-layout attribute")
    for col in db.collections.values():
        c_sz.add(col.size == 0x30 + 8 * col.types_len + 16 * col.num_entries, hx(col.export_key))
        cls = db.classes.get(col.class_key)
        if not c_cls.add(cls is not None, hx(col.class_key)):
            continue
        if col.parent_key:
            p = col
            seen = set()
            ok = True
            while p is not None and p.parent_key:
                if id(p) in seen:
                    ok = False
                    break
                seen.add(id(p))
                nxt = db.parent_of(p)
                if nxt is None:
                    ok = False
                    break
                p = nxt
            c_par.add(ok, (cls.name, col.name))
        c_lay.add((col.layout_ptr is not None) == (cls.layout_size > 0), (cls.name, col.name))
        c_tl.add(col.types_len == col.num_types + (col.num_types & 1), (cls.name, col.name, col.num_types, col.types_len))
        for e in col.entries:
            d = cls.by_key.get(e.key)
            if not c_key.add(d is not None, (cls.name, col.name, hx(e.key))):
                continue
            c_nolay.add(not d.in_layout, (cls.name, col.name, hx(e.key)))
            if not c_typ.add(e.type_index < col.num_types and col.type_keys[e.type_index] == d.type_key,
                             (cls.name, col.name, hx(e.key))):
                continue
            is_arr = bool(e.node_flags & NODE_ARRAY)
            inline = bool(e.node_flags & NODE_INLINE)
            has_ref = d.type.name == "Attrib::RefSpec" or d.type.name.startswith("Attrib::Gen::ClassRefSpec_")
            ok = (is_arr == d.is_array) and (e.entry_flags == 0) and not (e.node_flags & ~0x4A)
            if inline:
                ok = ok and d.size <= 4 and not is_arr and (e.ptr is None or d.type.name == "EA::Reflection::Text"
                                                              or d.size == 4)
            else:
                ok = ok and e.ptr is not None and (is_arr or d.size > 4)
            if e.node_flags & NODE_HAS_REFSPEC:
                ok = ok and (has_ref or is_arr)
            elif has_ref:
                ok = False
            c_fl.add(ok, (cls.name, col.name, hx(e.key), hex(e.node_flags), d.type.name))
            if is_arr and e.ptr is not None:
                alloc, count, esize, enc = struct.unpack_from(">HHHH", col.vault.bin, e.ptr)
                c_arr.add(esize == d.size and count <= alloc <= d.max_count and (enc & 0x7FFF) == 0
                          and bool(enc & 0x8000) == (d.alignment >= 4),
                          (cls.name, col.name, hx(e.key), alloc, count, esize, hex(enc), d.type.name))
        # in-layout arrays
        if col.layout_ptr is not None:
            for d in cls.defs:
                if d.in_layout and d.is_array:
                    alloc, count, esize, enc = struct.unpack_from(">HHHH", col.vault.bin, col.layout_ptr + d.offset)
                    c_arr.add(esize == d.size and count <= alloc <= d.max_count and (enc & 0x7FFF) == 0
                              and bool(enc & 0x8000) == (d.alignment >= 4),
                              (cls.name, col.name, hx(d.key), "layout", alloc, count, esize, hex(enc)))

    # 6 values
    c_txt = new("values: Text pointers resolve to printable strings")
    c_txs = new("values: Text targets lie in the StrE string pool")
    c_flt = new("values: Float attributes are plausible floats")
    c_fsel = new("values: Float attrs in dumped gameplay classes plausible")
    c_bool = new("values: Bool attributes are 0 or 1")
    c_ref = new("data: RefSpec class key resolves to a known class name")
    c_refc = new("data: RefSpec collection key resolves to a known name")
    c_ref.info = c_refc.info = True
    c_ref.note = c_refc.note = ("not a format check: unresolved targets live in vaults/classes that are not part of "
                                "skaterschema/skatercollections")
    c_vec = new("values: vector/matrix/colour components plausible floats")
    c_gr = new("values: graph floats plausible, x/y inside [min,max] header")
    nfloat_nonzero = 0
    vec_types = ("Attrib::Types::Vector2", "Attrib::Types::Vector3", "Attrib::Types::Vector4", "Math::Vector2",
                 "Math::Vector3", "Math::Vector4", "Attrib::Types::Matrix", "Attrib::Types::Quaternion",
                 "Attrib::Types::FloatColour")

    def visit(col, cls, d, vault, dep, off):
        nonlocal nfloat_nonzero
        b = vault.buf(dep)
        n = d.type.name
        if n == "EA::Reflection::Text":
            p = vault.fix[dep].get(off)
            raw = struct.unpack_from(">I", b, off)[0]
            if p is None:
                c_txt.add(raw == 0, (cls.name, col.name, d.label, "unfixed", hex(raw)))
                return
            s = vault.cstr(p[1]).decode("latin-1")
            c_txt.add(printable(s), (cls.name, col.name, d.label, s[:40]))
            c_txs.add(vault.stre[0] <= p[1] < vault.stre[1], (cls.name, col.name, hex(p[1])))
        elif n == "EA::Reflection::Float":
            x = struct.unpack_from(">f", b, off)[0]
            ok = float_plausible(x)
            c_flt.add(ok, (cls.name, col.name, d.label, x, b[off:off + 4].hex()))
            if cls.name.startswith(DUMP_PREFIXES):
                c_fsel.add(ok, (cls.name, col.name, d.label, x))
            if x != 0:
                nfloat_nonzero += 1
        elif n == "EA::Reflection::Bool":
            c_bool.add(b[off] in (0, 1), (cls.name, col.name, d.label, b[off]))
        elif n == "Attrib::RefSpec":
            ck, ok_ = struct.unpack_from(">QQ", b, off)
            if ck or ok_:
                c_ref.add(ck in db.names, (cls.name, col.name, d.label, hx(ck)))
                if ok_:
                    c_refc.add((ck, ok_) in db.collections or ok_ in db.names, (cls.name, col.name, d.label,
                                                                                 db.names.get(ck), hx(ok_)))
        elif n.startswith("Attrib::Gen::ClassRefSpec_"):
            ok_ = struct.unpack_from(">Q", b, off)[0]
            ck = hash64(n[len("Attrib::Gen::ClassRefSpec_"):])
            if ok_:
                c_refc.add((ck, ok_) in db.collections or ok_ in db.names, (cls.name, col.name, d.label,
                                                                             db.names.get(ck), hx(ok_)))
        elif n in vec_types:
            cnt = {"Attrib::Types::Vector2": 2, "Attrib::Types::Vector3": 3, "Attrib::Types::Matrix": 16}.get(n, 4)
            xs = struct.unpack_from(">%df" % cnt, b, off)
            c_vec.add(all(float_plausible(x) for x in xs), (cls.name, col.name, d.label, xs))
        elif n in GRAPH_TYPES:
            npts, neg = GRAPH_TYPES[n]
            fl = struct.unpack_from(">%df" % (2 * npts + (4 if neg else 0)), b, off)
            ok = all(float_plausible(x) for x in fl)
            if neg:
                mnx, mny, mxx, mxy = fl[:4]
                px, py = fl[4:4 + npts], fl[4 + npts:]
                ex = 1e-3 * max(1.0, abs(mxx - mnx))
                ey = 1e-3 * max(1.0, abs(mxy - mny))
                ok = ok and all(mnx - ex <= x <= mxx + ex for x in px) and all(mny - ey <= y <= mxy + ey for y in py)
            c_gr.add(ok, (cls.name, col.name, d.label, [f32_short(x) for x in fl[:8]]))

    for col in db.collections.values():
        cls = db.classes.get(col.class_key)
        if cls is None:
            continue
        v = col.vault
        for d in cls.defs:
            if d.type is None or d.is_static:
                continue
            if d.in_layout:
                if col.layout_ptr is None:
                    continue
                off = col.layout_ptr + d.offset
                if d.is_array:
                    alloc, count, esize, enc = struct.unpack_from(">HHHH", v.bin, off)
                    st = off + (16 if enc & 0x8000 else 8)
                    for i in range(min(count, d.max_count)):
                        visit(col, cls, d, v, 1, st + i * d.size)
                else:
                    visit(col, cls, d, v, 1, off)
            else:
                e = col.by_key.get(d.key)
                if e is None:
                    continue
                if e.node_flags & NODE_ARRAY:
                    alloc, count, esize, enc = struct.unpack_from(">HHHH", v.bin, e.ptr)
                    st = e.ptr + (16 if enc & 0x8000 else 8)
                    for i in range(count):
                        visit(col, cls, d, v, 1, st + i * d.size)
                elif e.node_flags & NODE_INLINE:
                    visit(col, cls, d, v, 0, e.data_off)
                elif e.ptr is not None:
                    visit(col, cls, d, v, 1, e.ptr)
    c_flt.note = "%d of the checked floats are non-zero" % nfloat_nonzero

    # 7 coverage of the .bin files: every byte is claimed by exactly one parsed object
    for v, title in ((db.schema_vault, "schema"), (db.coll_vault, "collections")):
        c_cov = new("coverage: %s .bin data fully explained by parse" % title)
        c_ovl = new("coverage: %s .bin parsed objects never overlap" % title)
        spans = []
        if v is db.schema_vault:
            spans.append((db.typenames_ptr, db.typenames_end, "typenames"))
            for cls in db.classes.values():
                if cls.definitions_ptr is not None:
                    spans.append((cls.definitions_ptr, cls.definitions_ptr + 24 * cls.num_definitions, "defs " + str(cls.name)))
                if cls.static_ptr is not None:
                    spans.append((cls.static_ptr, cls.static_ptr + cls.static_size, "static " + str(cls.name)))
        else:
            for col in db.collections.values():
                cls = db.classes.get(col.class_key)
                if cls is None:
                    continue
                if col.layout_ptr is not None:
                    used = max([d.offset + d.layout_span() for d in cls.defs if d.in_layout] or [0])
                    spans.append((col.layout_ptr, col.layout_ptr + used, "layout %s/%s" % (cls.name, col.name)))
                for e in col.entries:
                    d = cls.by_key.get(e.key)
                    if d is None or e.ptr is None or (e.node_flags & NODE_INLINE):
                        continue
                    if e.node_flags & NODE_ARRAY:
                        alloc, count, esize, enc = struct.unpack_from(">HHHH", v.bin, e.ptr)
                        spans.append((e.ptr, e.ptr + (16 if enc & 0x8000 else 8) + alloc * esize,
                                      "array %s/%s %s" % (cls.name, col.name, d.label)))
                    else:
                        spans.append((e.ptr, e.ptr + d.size, "data %s/%s %s" % (cls.name, col.name, d.label)))
                        if d.type.name == "Attrib::Blob":
                            bsz = struct.unpack_from(">I", v.bin, e.ptr)[0]
                            bp = v.fix[1].get(e.ptr + 4)
                            if bp and bsz:
                                spans.append((bp[1], bp[1] + bsz, "blob %s/%s %s" % (cls.name, col.name, d.label)))
        spans.sort()
        pos = v.bin_data_start
        unexplained = 0
        for a, b, what in spans:
            if a < v.bin_data_start:
                continue
            if a < pos:
                c_ovl.add(False, (what, hex(a), hex(pos)))
            else:
                c_ovl.add(True)
                gap = v.bin[pos:a]
                if len(gap) >= 16 or any(gap):
                    unexplained += len(gap)
                    c_cov.add(False, ("gap", hex(pos), hex(a), gap[:16].hex()))
                else:
                    c_cov.add(True)
            pos = max(pos, b)
        gap = v.bin[pos:]
        c_cov.add(len(gap) < 16 and not any(gap), ("tail gap", hex(pos), hex(len(v.bin))))
        c_cov.note = "%d objects; %d bytes outside any parsed object and not alignment padding" % (len(spans), unexplained)

    # 8 string pool coverage
    v = db.coll_vault
    c_str = new("coverage: every StrE string is referenced by a pointer")
    targets = set(t for dep in (0, 1) for (_, t) in v.fix[dep].values() if v.stre[0] <= t < v.stre[1])
    o = v.stre[0]
    pool_end = v.stre[1]
    while o < pool_end:
        end = v.bin.find(b"\0", o, pool_end)
        if end < 0:
            break
        if end == o and not any(v.bin[o:pool_end]) and o not in targets:
            break                       # trailing zero padding of the chunk
        c_str.add(o in targets, (hex(o), v.bin[o:end][:40]))
        o = end + 1

    total_ok = sum(c.ok for c in checks if not c.info)
    total_bad = sum(c.bad for c in checks if not c.info)
    if verbose:
        print("vlt_parse self-test")
        print("  schema      : %s (%d classes, %d types, %d definitions)" % (
            db.schema_vault.vlt_path, len(db.classes), len(db.types), sum(len(c.defs) for c in db.classes.values())))
        print("  collections : %s (%d collections)" % (db.coll_vault.vlt_path, len(db.collections)))
        print("  DatabaseLoadData: mNumClasses=%d mDefaultDataSize=%d mNumTypes=%d" % (
            db.db_num_classes, db.db_default_data_size, len(db.types)))
        print("  pointer fixups: schema vlt %d / bin %d ; collections vlt %d / bin %d" % (
            len(db.schema_vault.fix[0]), len(db.schema_vault.fix[1]), len(db.coll_vault.fix[0]), len(db.coll_vault.fix[1])))
        for c in checks:
            print(c.line())
        print("TOTAL: %d checks passed, %d failed (%d test groups, %d with failures; INFO lines not counted)" % (
            total_ok, total_bad, sum(1 for c in checks if not c.info), sum(1 for c in checks if c.bad and not c.info)))
        print("attribute names proven by hash: %d of %d distinct attribute keys" % (
            len({d.key for c in db.classes.values() for d in c.defs if d.name}),
            len({d.key for c in db.classes.values() for d in c.defs})))
    return checks


# --------------------------------------------------------------------------- CLI
def show(db, name):
    cls = db.cls(name)
    j = db.class_json(cls)
    print(json.dumps(j, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB_DIR, help="folder holding skaterschema.vlt/.bin and skatercollections.vlt/.bin")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dump", metavar="DIR", help="write <class>.json for the gameplay classes")
    ap.add_argument("--all", action="store_true", help="with --dump: every class, not only gameplay prefixes")
    ap.add_argument("--show", metavar="CLASS", help="print one class as JSON")
    ap.add_argument("--names", metavar="JSON", help="names.json to use (default: next to this script)")
    a = ap.parse_args()
    db = Database(a.db, names_path=a.names)
    did = False
    if a.selftest:
        checks = selftest(db)
        did = True
    if a.dump:
        n = db.dump(a.dump, ("",) if a.all else DUMP_PREFIXES)
        print("wrote %d class files to %s" % (n, a.dump))
        did = True
    if a.show:
        show(db, a.show)
        did = True
    if not did:
        ap.print_help()
    if a.selftest and any(c.bad for c in checks if not c.info):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
