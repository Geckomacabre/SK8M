"""Is the stance switch seamless?

Rolling fakie, the controller plays R_SWITCH_RIDE_N_0_N, then turns the ped by 180 degrees and starts the riding
pose of the OTHER clip set without a cross-fade. That only looks right if the switch clip's last frame is the other
set's riding pose seen from behind. Measured here on the GTA skeleton: both poses are put on the same board (their
feet anchors together) and the main joints compared in the world.

usage: python switch_pose.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402
import skate_fk as S  # noqa: E402

JOINTS = ('SKEL_Pelvis', 'SKEL_Spine3', 'SKEL_Head', 'SKEL_L_Hand', 'SKEL_R_Hand', 'SKEL_L_Calf', 'SKEL_R_Calf',
          'SKEL_L_Foot', 'SKEL_R_Foot')


def pose(rt, rig, frame, mirror):
    """Entity-space positions of every bone, and the feet anchor, for one decoded frame."""
    root_pos, local, _, feet = rt.frame(frame, mirror)
    wq, pos = {}, {}
    for n in rig.order:
        b = rig.bones[n]
        if b["parent"] is None:
            wq[n], pos[n] = rig.world_q(n), root_pos
            continue
        pw = wq[b["parent"]]
        wq[n] = T.qmul(pw, local[n]) if n in local else T.qmul(pw, tuple(b["local_q"]))
        pos[n] = T.vadd(pos[b["parent"]], T.qrot(pw, rig.offset.get(n, (0, 0, 0))))
    ent = {n: T.to_entity(p) for n, p in pos.items()}
    anchor = T.vmul(T.vadd(T.contact(feet, 'R'), T.contact(feet, 'L')), 0.5)
    return ent, anchor


def main():
    rig = T.Rig()
    rest = S.load_clip(os.path.join(T.CSV_DIR, "RIG_TPOSE.csv"))[0]
    rt = T.Retargeter(rig, rest)
    switch = S.load_clip(os.path.join(T.CSV_DIR, "R_SWITCH_RIDE_N_0_N.csv"))
    idle = S.load_clip(os.path.join(T.CSV_DIR, "R_IDLE_HCOM_000.csv"))
    ok = True
    for label, mirror in (("goofy -> switch (authored clip, then the mirrored set)", False),
                          ("regular -> switch (mirrored clip, then the authored set)", True)):
        a, anchor_a = pose(rt, rig, switch[-1], mirror)          # where the switch clip leaves the body
        b, anchor_b = pose(rt, rig, idle[0], not mirror)         # the other set's riding pose ...
        worst, worst_joint = 0.0, None
        for j in JOINTS:
            pa = T.vsub(a[j], anchor_a)
            pb = T.vsub(b[j], anchor_b)
            pb = (-pb[0], -pb[1], pb[2])                         # ... seen from behind (ped turned 180 degrees)
            d = math.dist(pa, pb)
            if d > worst:
                worst, worst_joint = d, j
        good = worst < 0.08
        ok &= good
        print(f"{'OK ' if good else 'BAD'} {label}: joints within {worst * 100:.1f} cm ({worst_joint})")
        # and the clip must START in this set's own riding pose
        s0, anchor_s = pose(rt, rig, switch[0], mirror)
        i0, anchor_i = pose(rt, rig, idle[0], mirror)
        start = max(math.dist(T.vsub(s0[j], anchor_s), T.vsub(i0[j], anchor_i)) for j in JOINTS)
        good = start < 0.08
        ok &= good
        print(f"{'OK ' if good else 'BAD'}    it starts in the riding pose: joints within {start * 100:.1f} cm")
    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
