"""End-to-end check of what the game will actually load.

For every clip the controller plays (and its mirrored copy): take the COMPILED dictionary (.ycd, as streamed to the
game), turn it back into XML with CodeWalker, pose the GTA skeleton with it using the forward kinematics that
`vanilla_oracle.py` proved against Rockstar's own clips, and compare where the feet end up with the deck position the
board track says ("anchor") for the same frame. If the two agree, the board the script places is under the feet the
game draws.

  two-foot clips: the anchor must be the midpoint under both feet
  one-foot clips (push, brake, foot-down stand): the anchor follows the foot that stays on the board
  the coffin (the rider lies on the board, feet out past its end): the deck is in line with the feet and at their
      height, but along the board it is under the hips - the hip bone of the compiled clip has to be over it

usage: python ycd_roundtrip.py [dict ...]     (default: every dictionary a controller clip lives in)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402
import export_all  # noqa: E402
import vanilla_oracle as VO  # noqa: E402

YCD = export_all.OUT
ROW = re.compile(r"\{([-\d.e,]+)\}")   # 7 numbers, or 11 for an off-board clip (see s3_to_ycd.carry_rows)


def load_tracks(dict_name):
    """clip -> [(qx, qy, qz, qw, ax, ay, az)] from the generated <dict>_board.lua."""
    out = {}
    for line in open(os.path.join(YCD, dict_name + "_board.lua")):
        m = re.match(r'SkateBoardTracks\["[^/]+/([^"]+)"\] = \{fps=([\d.]+), (?:hand=true, |grip1=\{[^}]*\}, )?frames=\{(.*)\}\}', line)
        if m:
            out[m.group(1)] = [tuple(float(v) for v in row.split(',')) for row in ROW.findall(m.group(3))]
    return out


def to_xml(dict_name, tmp):
    out = os.path.join(tmp, dict_name + ".rt.xml")
    r = subprocess.run([export_all.CWTOOL], capture_output=True, text=True, input=json.dumps(
        {"cmd": "toxml", "in": os.path.join(YCD, dict_name + ".ycd"), "out": out}))
    res = json.loads(r.stdout or "{}")
    if not os.path.exists(out):
        raise RuntimeError(f"cwtool could not read {dict_name}.ycd: {res}")
    return out


def main():
    index = json.load(open(os.path.join(YCD, "clip_index.json")))
    played = [c.lower() for c in export_all.controller_clips()]
    want = {}
    for c in played:
        for name in (c, c + '_mir'):
            if name in index:
                want.setdefault(index[name], set()).add(name)
    only = set(sys.argv[1:])
    rig = T.Rig()
    stance = None
    ok, worst_all, n_clips, lying_worst, carry_worst = True, 0.0, 0, 0.0, 0.0
    with tempfile.TemporaryDirectory() as tmp:
        # the riding stance (each foot's offset from the deck centre), from the compiled riding clip itself
        for dict_name in sorted(want):
            if only and dict_name not in only:
                continue
            tracks = load_tracks(dict_name)
            root = ET.parse(to_xml(dict_name, tmp)).getroot()
            anims = {a.find('Hash').text: a for a in root.find('Animations')}
            worst, worst_clip, count = 0.0, None, 0
            for clip in sorted(want[dict_name]):
                anim = anims.get(clip)
                track = tracks.get(clip)
                if anim is None or track is None:
                    print(f"BAD {dict_name}/{clip}: missing from the compiled dictionary or the track file")
                    ok = False
                    continue
                dec, n = VO.decode(anim)
                if n != len(track):
                    print(f"BAD {dict_name}/{clip}: {n} frames in the ycd, {len(track)} in the track")
                    ok = False
                    continue
                mirror = clip.endswith('_mir')
                base = clip[:-4] if mirror else clip
                side = T.one_foot(base)
                if mirror and side:
                    side = 'L' if side == 'R' else 'R'
                if side and stance is None:
                    stance = riding_stance(rig, tmp)
                for f in sorted({0, n // 3, (2 * n) // 3, n - 1}):
                    wq, pos, _, _ = VO.fk(rig, dec, f)
                    con = {}
                    for s in 'RL':
                        ankle, toe = pos[f'SKEL_{s}_Foot'], pos[f'SKEL_{s}_Toe0']
                        con[s] = (toe[0] * 0.7 + ankle[0] * 0.3, toe[1] * 0.7 + ankle[1] * 0.3,
                                  min(toe[2] - T.TOE_ABOVE_SOLE, ankle[2] - T.ANKLE_ABOVE_SOLE))
                    if side:
                        st = stance[side] if not mirror else T.mirror_v(stance['L' if side == 'R' else 'R'])
                        expect = T.vsub(con[side], st)
                    else:
                        expect = T.vmul(T.vadd(con['R'], con['L']), 0.5)
                    err = T.length(T.vsub(expect, track[f][4:7]))
                    if len(track[f]) == 11:
                        # an off-board clip: its anchor is the ground under the rider, not the deck. Standing, the
                        # lower sole has to be on that ground (within 3 cm); in the other clips a foot may be in the
                        # air at any of the frames looked at, so only the stand is held to it
                        err = 0.0
                        if '_stand_0_cyc' in base:
                            gap = abs(min(con['R'][2], con['L'][2]) - track[f][6])
                            carry_worst = max(carry_worst, gap)
                            if gap > 0.03:
                                err = max(gap, 0.01)
                    if T.lying(base):
                        # sideways and in height as the feet say; along the board the hips are over the deck
                        # (within 15 cm once the rider lies, in the cycles) and the feet are well out past it
                        hips = pos['SKEL_Pelvis']
                        err = max(abs(expect[0] - track[f][4]), abs(expect[2] - track[f][6]))
                        if base.endswith('_cyc'):
                            off = abs(hips[1] - track[f][5])
                            lying_worst = max(lying_worst, off)
                            if off > 0.15 or abs(expect[1] - track[f][5]) < 0.5:
                                err = max(err, off, 0.5)
                    if err > worst:
                        worst, worst_clip = err, f"{clip} frame {f}"
                count += 1
            n_clips += count
            worst_all = max(worst_all, worst)
            good = worst < 0.005
            ok &= good
            print(f"{'OK ' if good else 'BAD'} {dict_name}: {count} clips, feet (from the compiled ycd) vs baked anchor: "
                  f"worst {worst * 1000:.1f} mm ({worst_clip})")
    print(f"{n_clips} clips checked, worst {worst_all * 1000:.1f} mm; lying in the coffin the hips are within "
          f"{lying_worst * 100:.0f} cm of the middle of the deck along the board; standing off the board the soles are "
          f"within {carry_worst * 100:.1f} cm of the ground")
    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


def riding_stance(rig, tmp):
    """Each foot's offset from the deck centre in the plain riding pose, measured on the compiled clip."""
    root = ET.parse(to_xml('skate3@r', tmp)).getroot()
    anim = {a.find('Hash').text: a for a in root.find('Animations')}['r_idle_hcom_000']
    dec, _ = VO.decode(anim)
    _, pos, _, _ = VO.fk(rig, dec, 0)
    con = {}
    for s in 'RL':
        ankle, toe = pos[f'SKEL_{s}_Foot'], pos[f'SKEL_{s}_Toe0']
        con[s] = (toe[0] * 0.7 + ankle[0] * 0.3, toe[1] * 0.7 + ankle[1] * 0.3,
                  min(toe[2] - T.TOE_ABOVE_SOLE, ankle[2] - T.ANKLE_ABOVE_SOLE))
    mid = T.vmul(T.vadd(con['R'], con['L']), 0.5)
    return {s: T.vsub(con[s], mid) for s in 'RL'}


if __name__ == "__main__":
    main()
