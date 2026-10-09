"""Offline check of the converted geometry: is the board under the retargeted GTA feet, and lined up with them?

For each clip the controller plays, every frame, in ped (entity) space:
  - the board's long axis (from the baked board track) should run along the line between the two feet
  - the deck centre ("anchor") should sit at the soles, between the feet
  - the board should run along the ped's forward axis while riding (the ped faces the way the board rolls)
Uses the same retarget as the converter (s3_to_ycd.Retargeter) on the GTA skeleton it was baked for.

usage: python board_geometry.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402
import skate_fk as S  # noqa: E402

# (clip, frames where both feet are on the deck: 'all' or 'first' for clips that leave the ground)
CLIPS = [
    ('R_IDLE_HCOM_000', 'all'), ('R_IDLE_LCOM_000', 'all'), ('R_IDLE_HCOM_N100', 'all'), ('R_IDLE_HCOM_P100', 'all'),
    ('R_ANTIC_OLLIE_N_0_CYC', 'all'), ('R_ANTIC_NOLLIE_N_0_CYC', 'all'), ('M_IDLE_N_0_CYC', 'all'),
    ('G_5050_FS_HI_0_CYC', 'all'), ('G_BSLIDE_FS_HI_0_CYC', 'all'), ('IA_IDLE_N_N_0_CYC', 'all'),
    ('OLLIE_HIGH_G', 'first'), ('KICKFLIP_IN_HIGH_G', 'first'), ('L_HCOM_LIMP', 'all'),
]


def main():
    rig = T.Rig()
    rest = S.load_clip(os.path.join(T.CSV_DIR, "RIG_TPOSE.csv"))[0]
    rt = T.Retargeter(rig, rest)
    stance = T.riding_stance(rt)
    print(f"riding stance (front foot R, back foot L, from the deck centre, ped space): "
          f"R {tuple(round(v, 3) for v in stance['R'])}  L {tuple(round(v, 3) for v in stance['L'])}")
    ok = True
    for clip, which in CLIPS:
        data = S.load_clip(os.path.join(T.CSV_DIR, clip + ".csv"))
        frames = [rt.frame(fr) for fr in data]
        anchors = T.anchors(clip, [f[3] for f in frames], stance)
        idx = range(len(frames)) if which == 'all' else [0]
        worst_axis, worst_mid, worst_up, worst_fwd, gaps = 0.0, 0.0, 0.0, 0.0, []
        for i in idx:
            _, _, (bpos, bq), feet = frames[i][:4]
            q = T.qnorm(T.qmul(T.R180, bq))  # what the track stores
            axis, up = T.qrot(q, (0, 1, 0)), T.qrot(q, (0, 0, 1))
            r, l = T.contact(feet, 'R'), T.contact(feet, 'L')
            between = T.vsub(r, l)
            # angle between the foot-to-foot line and the board's long axis, inside the deck plane
            flat = T.vsub(between, T.vmul(up, T.dot(between, up)))
            ang = math.degrees(math.acos(min(1.0, abs(T.dot(T.norm(flat), axis)))))
            mid = T.vmul(T.vadd(r, l), 0.5)
            a = anchors[i]
            worst_axis = max(worst_axis, ang)
            worst_mid = max(worst_mid, T.length(T.vsub(mid, a)))
            # how far each sole is off the deck plane through the anchor
            worst_up = max(worst_up, abs(T.dot(T.vsub(r, a), up)), abs(T.dot(T.vsub(l, a), up)))
            worst_fwd = max(worst_fwd, math.degrees(math.acos(min(1.0, abs(axis[1])))))
            gaps.append(T.length(between))
        good = worst_axis < 20 and worst_mid < 0.03 and worst_up < 0.06 and 0.3 < min(gaps) and max(gaps) < 0.75
        ok &= good
        print(f"{'OK ' if good else 'BAD'} {clip:24s} feet-line vs board {worst_axis:5.1f} deg  "
              f"anchor vs feet midpoint {worst_mid * 100:4.1f} cm  soles off the deck {worst_up * 100:4.1f} cm  "
              f"feet apart {min(gaps):.2f}-{max(gaps):.2f} m  board vs ped forward {worst_fwd:5.1f} deg")
    print("ALL OK" if ok else "FAILURES")


if __name__ == "__main__":
    main()
