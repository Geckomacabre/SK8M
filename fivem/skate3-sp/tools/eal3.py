"""Skate 3's sounds -> PCM. Runs on YOUR copy of the game; what it writes stays on your machine.

Skate 3 keeps its sound effects as "EALayer3" (EA's repacking of MPEG audio layer III) inside .abk / .bnk banks,
.snr files and .grain files. Each sample is an SNR header, one or more blocks, and in each block a run of
EA-frames: one MPEG granule each, with the side info squeezed and the main data cut to its exact length. This
module finds the samples in a file, turns the EA-frames back into an ordinary MP3 stream (two granules per frame
for MPEG-1, one for MPEG-2) and lets ffmpeg decode that.

    SNR header   u32  version:4 codec:4 channels-1:6 sample_rate:18
                 u32  type:2 loop:1 num_samples:29      (+ u32 loop start when loop is set)
    block        u32  flags:8 size:24 (the block's size, this header included)   u32 samples in the block
    EA-frame v1 (codec 5)   u8 pcm flag (0xEE = raw PCM follows), common part, [u16 offset, u16 pcm samples, u32 0, PCM]
    EA-frame v2 (codec 6/7) u16 extended:1 stereo:1 unused:2 frame_size:12, [u32 mode:2 offset:10 pcm:10 common_size:10],
                            common part, [PCM]
    common part  version:2 sample_rate:2 channel_mode:2 mode_extension:2 granule:1 [scfsi:4 per channel, 2nd granule
                 of MPEG-1 only], then per channel main_data_bits:12 + the rest of that channel's side info
                 (47 bits MPEG-1, 51 bits MPEG-2), then the main data, padded to a whole byte

The layout follows vgmstream's description of the format (mpeg_custom_utils_ealayer3.c). Every v2 frame carries its
own size and every block its own length, and both are checked against what this parser works out, so a wrong
reading shows at once.

usage: python eal3.py <file> [...]            list the samples found
       python eal3.py <file> --wav <out_dir>  decode them all to .wav
"""
import os
import shutil
import struct
import subprocess
import sys
import wave

import numpy as np

FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"   # (set FFMPEG if it is not on the path)
RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}  # by MPEG version index
KNOWN_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
DELAY = 1105  # where the sound starts in what an MP3 decoder gives back


class Bits:
    def __init__(self, data, byte=0):
        self.d, self.p = data, byte * 8

    def get(self, n):
        if n == 0:
            return 0
        p = self.p
        first, last = p >> 3, (p + n - 1) >> 3
        v = int.from_bytes(self.d[first:last + 1], "big")
        self.p = p + n
        return (v >> ((last + 1) * 8 - p - n)) & ((1 << n) - 1)


class Out:
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, n, value):
        self.v = (self.v << n) | (value & ((1 << n) - 1))
        self.n += n

    def bytes(self):
        pad = -self.n % 8
        return (self.v << pad).to_bytes((self.n + pad) // 8, "big")


class Bad(Exception):
    pass


def common(data, byte):
    """The common part of an EA-frame starting at `byte`. Returns its fields and its size in bytes."""
    b = Bits(data, byte)
    f = {"vi": b.get(2), "sri": b.get(2), "mode": b.get(2), "ext": b.get(2)}
    if f["vi"] == 1 or f["sri"] == 3:
        raise Bad("not an MPEG header")
    f["mpeg1"] = f["vi"] == 3
    f["channels"] = 1 if f["mode"] == 3 else 2
    f["rate"] = RATES[f["vi"]][f["sri"]]
    f["granule"] = b.get(1)
    f["scfsi"] = [b.get(4) for _ in range(f["channels"])] if (f["mpeg1"] and f["granule"] == 1) else [0] * f["channels"]
    rest = 47 if f["mpeg1"] else 51
    f["bits"], f["side"] = [], []
    for _ in range(f["channels"]):
        f["bits"].append(b.get(12))
        f["side"].append(b.get(rest))
    f["data"] = b.p                     # bit offset of the main data
    total = (b.p - byte * 8) + sum(f["bits"])
    if byte + (total + 7) // 8 > len(data):
        raise Bad("frame runs past the end")
    return f, (total + 7) // 8


def frames(data, start, end, codec, channels):
    """The EA-frames of one block: (fields or None for a PCM-only frame, pcm samples as int16 array or None)."""
    out, p = [], start
    while p < end:
        if codec == 5:
            flag = data[p]
            f, size = common(data, p + 1)
            q = p + 1 + size
            pcm = None
            if flag == 0xEE:
                offset, count, unknown = struct.unpack_from(">HHI", data, q)   # the last field is always 0
                q += 8
                pcm = np.frombuffer(data, dtype=">i2", count=count * channels, offset=q).astype(np.int16)
                q += 2 * count * channels
                f["pcm_offset"] = offset
            elif flag != 0:
                raise Bad("v1 frame flag %#x at %#x" % (flag, p))
            out.append((f, pcm))
            p = q
        else:
            head = struct.unpack_from(">H", data, p)[0]
            extended, size = head >> 15, head & 0xFFF
            q, f, pcm, count, csize = p + 2, None, None, 0, None
            if extended:
                ext = struct.unpack_from(">I", data, q)[0]
                q += 4
                mode, offset, count, csize = ext >> 30, (ext >> 20) & 0x3FF, (ext >> 10) & 0x3FF, ext & 0x3FF
            if not extended or csize:
                f, got = common(data, q)
                if csize is not None and got != csize:
                    raise Bad("v2 common size %d, worked out %d at %#x" % (csize, got, p))
                q += got
                if extended:
                    f["pcm_offset"], f["pcm_mode"] = offset, mode
            if count:
                pcm = np.frombuffer(data, dtype=">i2", count=count * channels, offset=q).astype(np.int16)
                q += 2 * count * channels
            if q - p != size:
                raise Bad("v2 frame size %d, worked out %d at %#x" % (size, q - p, p))
            if size == 0:
                raise Bad("empty v2 frame at %#x" % p)
            out.append((f, pcm))
            p = q
    if p != end:
        raise Bad("frames end at %#x, the block at %#x" % (p, end))
    return out


def mp3_stream(data, granules, reservoir=True):
    """An ordinary MP3 stream from EA granules.

    Every frame is written at the highest bit rate, which fixes its size. A granule can still be bigger than its
    share of a frame, so the main data is laid out the way MP3 allows: a frame's data may start up to 511 bytes
    (255 for MPEG-2) back in the room earlier frames left free ("bit reservoir").
    """
    if not granules:
        return b"", 0
    first = granules[0]
    mpeg1, ch = first["mpeg1"], first["channels"]
    if mpeg1:
        groups = []
        for i in range(0, len(granules), 2):
            g0 = granules[i]
            if i + 1 < len(granules):
                g1 = granules[i + 1]
            else:                       # an odd granule at the end: pair it with an empty one
                g1 = dict(g0, bits=[0] * ch, side=[0] * ch, scfsi=[0] * ch, granule=1)
            if g0["granule"] != 0 or g1["granule"] != 1:
                raise Bad("MPEG-1 granules out of step")
            groups.append((g0, g1))
        size, side_bytes, back_max = 144 * 320000 // first["rate"], (17 if ch == 1 else 32), 511
    else:
        groups = [(g,) for g in granules]
        size, side_bytes, back_max = 72 * 160000 // first["rate"], (9 if ch == 1 else 17), 255
    if not reservoir:
        back_max = 0
    head = 4 + side_bytes
    room = size - head
    out = bytearray(size * len(groups))
    rest = 47 if mpeg1 else 51
    end_prev = 0                        # in main-data bytes: frame k's own room is [k * room, (k + 1) * room)
    for k, grs in enumerate(groups):
        g0 = grs[0]
        if any(g["vi"] != first["vi"] or g["sri"] != first["sri"] or g["channels"] != ch for g in grs):
            raise Bad("the stream changes format")
        m = Out()
        for g in grs:
            n = sum(g["bits"])
            if n:
                b = Bits(data)
                b.p = g["data"]
                m.put(n, b.get(n))
        main = m.bytes()
        begin = max(end_prev, k * room - back_max)
        if begin + len(main) > (k + 1) * room:
            raise Bad("more main data than MP3 frames hold (frame %d, %d bytes)" % (k, len(main)))
        end_prev = begin + len(main)
        o = Out()
        o.put(11, 0x7FF)
        o.put(2, g0["vi"])
        o.put(2, 1)             # layer III
        o.put(1, 1)             # no CRC
        o.put(4, 14)            # the highest bit rate
        o.put(2, g0["sri"])
        o.put(1, 0)             # padding
        o.put(1, 0)             # private
        o.put(2, g0["mode"])
        o.put(2, g0["ext"])
        o.put(1, 1)             # copyright
        o.put(1, 1)             # original
        o.put(2, 0)             # emphasis
        if mpeg1:
            o.put(9, k * room - begin)      # main_data_begin
            o.put(5 if ch == 1 else 3, 0)
            for c in range(ch):
                o.put(4, grs[1]["scfsi"][c])
        else:
            o.put(8, k * room - begin)
            o.put(1 if ch == 1 else 2, 0)
        for g in grs:
            for c in range(ch):
                o.put(12, g["bits"][c])
                o.put(rest, g["side"][c])
        hb = o.bytes()
        assert len(hb) == head, (len(hb), head)
        out[k * size:k * size + head] = hb
        pos = begin
        i = 0
        while i < len(main):                # the data runs through the rooms of the frames, skipping their headers
            fr, off = divmod(pos, room)
            n = min(room - off, len(main) - i)
            a = fr * size + head + off
            out[a:a + n] = main[i:i + n]
            pos += n
            i += n
    return bytes(out), len(groups)


class Sample:
    """One sample inside a file: where it is and what its header says."""

    def __init__(self, data, offset):
        h1, h2 = struct.unpack_from(">II", data, offset)
        self.data, self.offset = data, offset
        self.codec, self.channels, self.rate = (h1 >> 24) & 15, ((h1 >> 18) & 63) + 1, h1 & 0x3FFFF
        self.kind, self.loop, self.samples = h2 >> 30, (h2 >> 29) & 1, h2 & 0x1FFFFFFF
        p = offset + 8
        self.loop_start = None
        if self.loop:
            self.loop_start = struct.unpack_from(">I", data, p)[0]
            p += 4
        self.blocks = []        # (first frame, end, samples)
        total = 0
        while total < self.samples:
            size, count = struct.unpack_from(">II", data, p)
            size &= 0x00FFFFFF
            if size < 8 or p + size > len(data) or count == 0 or count > self.samples - total:
                raise Bad("block at %#x does not fit" % p)
            self.blocks.append((p + 8, p + size, count))
            total += count
            p += size
        self.end = p

    def parse(self):
        """Every EA-frame of the sample, in order."""
        eaf = []
        for a, b, _ in self.blocks:
            eaf += frames(self.data, a, b, self.codec, self.channels)
        return eaf

    def raw(self, ffmpeg=FFMPEG, reservoir=True):
        """What the MP3 decoder gives back for the whole sample, untrimmed: (int16 [n, channels], lead-in PCM,
        samples the decoder left out at the start)."""
        eaf = self.parse()
        ch = self.channels
        granules = [f for f, _ in eaf if f is not None]
        lead = [pcm for _, pcm in eaf if pcm is not None]
        self.granules = len(granules)
        head = np.concatenate(lead).reshape(-1, ch) if lead else np.zeros((0, ch), np.int16)
        if not granules:
            return np.zeros((0, ch), np.int16), head, 0
        mp3, nframes = mp3_stream(self.data, granules, reservoir)
        r = subprocess.run([ffmpeg, "-v", "error", "-f", "mp3", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le",
                            "-ac", str(ch), "pipe:1"], input=mp3, capture_output=True)
        if r.returncode != 0 or r.stderr.strip():
            raise Bad("ffmpeg: " + r.stderr.decode("utf-8", "replace")[:300])
        dec = np.frombuffer(r.stdout, dtype="<i2").reshape(-1, ch)
        expected = nframes * (1152 if granules[0]["mpeg1"] else 576)
        return dec, head, expected - len(dec)

    def decode(self, ffmpeg=FFMPEG):
        """int16 samples, shape (num_samples, channels)."""
        dec, head, skipped = self.raw(ffmpeg)
        self.lead, self.decoded = len(head), len(dec)
        start = max(0, DELAY - skipped) + len(head)
        out = np.concatenate([head, dec[start:start + max(0, self.samples - len(head))]])
        if len(out) < self.samples:
            out = np.concatenate([out, np.zeros((self.samples - len(out), self.channels), np.int16)])
        return out[:self.samples]


def find(data):
    """Every sample in a file (a bank, a .snr or a .grain)."""
    out, i, n = [], 0, len(data) - 16
    while i < n:
        b0 = data[i]
        if (b0 >> 4) in (0, 1) and (b0 & 15) in (5, 6, 7):
            h1, h2 = struct.unpack_from(">II", data, i)
            if (h1 & 0x3FFFF) in KNOWN_RATES and ((h1 >> 18) & 63) < 2 and (h2 >> 30) == 0 and 200 < (h2 & 0x1FFFFFFF) < 48000 * 180:
                try:
                    s = Sample(data, i)
                    s.parse()
                    out.append(s)
                    i = s.end
                    continue
                except (Bad, struct.error, IndexError, ValueError):
                    pass
        i += 1
    return out


def write_wav(path, pcm, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype("<i2").tobytes())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_dir = sys.argv[sys.argv.index("--wav") + 1] if "--wav" in sys.argv else None
    if out_dir:
        args = [a for a in args if a != out_dir]
        os.makedirs(out_dir, exist_ok=True)
    for path in args:
        data = open(path, "rb").read()
        found = find(data)
        base = os.path.splitext(os.path.basename(path))[0]
        print("%s: %d samples" % (path, len(found)))
        for k, s in enumerate(found):
            line = "  %3d  at %#8x  codec %d  %d Hz  %d ch  %7d samples (%.2f s)%s" % (
                k, s.offset, s.codec, s.rate, s.channels, s.samples, s.samples / s.rate, "  loop" if s.loop else "")
            if out_dir:
                try:
                    pcm = s.decode()
                    write_wav(os.path.join(out_dir, "%s_%03d.wav" % (base, k)), pcm, s.rate)
                    line += "  lead-in PCM %d, peak %d" % (s.lead, int(np.abs(pcm).max()) if len(pcm) else 0)
                except Bad as e:
                    line += "  FAILED: %s" % e
            print(line)


if __name__ == "__main__":
    main()
