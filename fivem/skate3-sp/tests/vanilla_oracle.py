"""Does our idea of GTA's ped-animation conventions match the game's own clips?

The converter assumes: track 1 = each bone's rotation relative to its parent, bone 0 track 0/1 = the root's position and
rotation in ENTITY space (x right, y forward, z up), root rotation ~identity (which turns the -Y facing bind pose to face
+Y). If that is right, running one of Rockstar's own standing clips through the same forward kinematics as the converter
(same rig file, same bone offsets) must give a ped that stands upright, faces +Y, has its left foot on -X and its soles
about 1 m under the entity origin.

Input: a vanilla clip dictionary exported to CodeWalker XML (from your own GTA V install).

usage: python vanilla_oracle.py <dict.ycd.xml> [clip-name-substring]
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402


def floats(text):
    return [float(v) for v in text.split()]


def channel_values(ch, n):
    """One CodeWalker channel -> list of per-frame values (floats, or quaternion/vector tuples for static ones)."""
    typ = ch.find('Type').attrib['value']
    if typ == 'StaticFloat':
        return 'f', [float(ch.find('Value').attrib['value'])] * n
    if typ in ('QuantizeFloat', 'RawFloat', 'LinearFloat', 'IndirectQuantizeFloat'):
        vals = floats(ch.find('Values').text)
        if typ == 'IndirectQuantizeFloat':
            frames = [int(v) for v in ch.find('Frames').text.split()]
            vals = [vals[i] for i in frames]
        return 'f', (vals + [vals[-1]] * n)[:n]
    if typ == 'StaticQuaternion':
        v = ch.find('Value').attrib
        return 'q', [(float(v['x']), float(v['y']), float(v['z']), float(v['w']))] * n
    if typ == 'StaticVector3':
        v = ch.find('Value').attrib
        return 'v', [(float(v['x']), float(v['y']), float(v['z']))] * n
    if typ in ('CachedQuaternion1', 'CachedQuaternion2'):
        return 'c', int(ch.find('QuatIndex').attrib['value'])
    raise ValueError('channel type ' + typ)


def decode(anim):
    """Animation element -> {(bone tag, track): [per-frame value]} (quaternions x,y,z,w / vectors)."""
    n = int(anim.find('FrameCount').attrib['value'])
    ids = [(int(b.find('BoneId').attrib['value']), int(b.find('Track').attrib['value']))
           for b in anim.find('BoneIds')]
    seqs = list(anim.find('Sequences'))
    out = {}
    start = 0
    for seq in seqs:
        cnt = int(seq.find('FrameCount').attrib['value'])
        for (tag, track), item in zip(ids, seq.find('SequenceData')):
            chans = [channel_values(c, cnt) for c in item.find('Channels')]
            kinds = [k for k, _ in chans]
            if kinds == ['q'] or kinds == ['v']:
                vals = chans[0][1]
            elif 'c' in kinds:
                # three stored components, the fourth (index QuatIndex) rebuilt so the quaternion has unit length
                missing = chans[kinds.index('c')][1]
                comp = [c[1] for c in chans if c[0] == 'f']
                vals = []
                for f in range(cnt):
                    three = [c[f] for c in comp]
                    w = math.sqrt(max(0.0, 1.0 - sum(v * v for v in three)))
                    three.insert(missing, w)
                    vals.append(tuple(three))
            elif len(chans) in (3, 4):
                vals = [tuple(c[1][f] for c in chans) for f in range(cnt)]
            elif len(chans) == 1:
                vals = chans[0][1]
            else:
                raise ValueError(f'{tag}/{track}: {kinds}')
            out.setdefault((tag, track), []).extend(vals)
        start += cnt
    return out, n


def fk(rig, tracks, frame):
    """World (entity-space) rotation and position per bone for one frame, the way the converter's FK does it."""
    by_tag = {b['tag']: b['name'] for b in rig.bones.values()}
    rot, pos_t = {}, {}
    for (tag, track), vals in tracks.items():
        name = by_tag.get(tag)
        if name is None:
            continue
        v = vals[min(frame, len(vals) - 1)]
        if track == 1 and len(v) == 4:
            rot[name] = T.qnorm(v)
        elif track == 0 and len(v) == 3:
            pos_t[name] = v
    wq, pos = {}, {}
    for n in rig.order:
        b = rig.bones[n]
        if b['parent'] is None:
            wq[n] = rot.get(n, (0.0, 0.0, 0.0, 1.0))
            pos[n] = pos_t.get(n, (0.0, 0.0, 0.0))
            continue
        p = b['parent']
        local = rot.get(n, tuple(b['local_q']))
        wq[n] = T.qnorm(T.qmul(wq[p], local))
        offset = pos_t.get(n, tuple(b['local_t']))
        pos[n] = T.vadd(pos[p], T.qrot(wq[p], offset))
    return wq, pos, rot, pos_t


def main():
    path = sys.argv[1]
    want = sys.argv[2].lower() if len(sys.argv) > 2 else ''
    root = ET.parse(path).getroot()
    anims = {a.find('Hash').text: a for a in root.find('Animations')}
    rig = T.Rig()
    ok = True
    for clip in root.find('Clips'):
        name = clip.find('Hash').text
        if want and want not in name.lower():
            continue
        if clip.find('AnimationHash') is not None:
            hashes = [clip.find('AnimationHash').text]
        else:
            hashes = [a.find('AnimationHash').text for a in clip.find('Animations')]
        tracks = {}
        for h in hashes:
            t, _ = decode(anims[h])
            tracks.update(t)
        wq, pos, rot, pos_t = fk(rig, tracks, 0)
        rq = rot.get('SKEL_ROOT', (0, 0, 0, 1))
        la, lt = pos['SKEL_L_Foot'], pos['SKEL_L_Toe0']
        ra, rt = pos['SKEL_R_Foot'], pos['SKEL_R_Toe0']
        head = pos['SKEL_Head']
        sole = min(lt[2] - T.TOE_ABOVE_SOLE, la[2] - T.ANKLE_ABOVE_SOLE, rt[2] - T.TOE_ABOVE_SOLE,
                   ra[2] - T.ANKLE_ABOVE_SOLE)
        facing = ((lt[0] - la[0]) + (rt[0] - ra[0]), (lt[1] - la[1]) + (rt[1] - ra[1]))
        fl = math.hypot(*facing)
        checks = [
            (f"root rotation ~identity {tuple(round(v, 3) for v in rq)}", abs(abs(rq[3]) - 1.0) < 0.05),
            (f"head above the origin (z {head[2]:+.2f})", 0.5 < head[2] < 0.9),
            (f"soles about 1 m under the origin (z {sole:+.3f})", -1.06 < sole < -0.94),
            (f"toes point to +Y (forward {facing[1] / fl:+.2f})", facing[1] / fl > 0.7),
            (f"left foot on -X, right foot on +X (L x {la[0]:+.2f}, R x {ra[0]:+.2f})", la[0] < -0.03 < 0.03 < ra[0]),
        ]
        print(f"{name}: {len(tracks)} tracks, root pos track {pos_t.get('SKEL_ROOT')}")
        for label, good in checks:
            ok &= good
            print(("  OK  " if good else "  BAD ") + label)
    print("CONVENTIONS CONFIRMED" if ok else "MISMATCH")


if __name__ == "__main__":
    main()
