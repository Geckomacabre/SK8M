"""Is the GTA body where Skate 3's is? The converter's fit (s3_to_ycd.Retargeter, the method of SK8V's ped.rs)
measured against Skate 3's own joints, clip by clip, with the old rotation-only retarget as the control.

Per clip, the worst frame:
  hips    the middle of GTA's hip joints against Skate 3's (cm)
  ankles  GTA's ankles against Skate 3's, once the common offset of the two is taken out: the board is put under the
          feet, so only where the feet are against each other shows (cm)
  sole    the angle between GTA's sole and Skate 3's (degrees)
  hand    for clips with a hand on the deck: that wrist against Skate 3's, measured from the feet (cm), over the
          frames in which Skate 3's own hand is at the deck
  knee    GTA's knees against Skate 3's (cm): the bones differ by a centimetre, a knee bent the wrong way is 20 off
  pop     the most a leg or arm bone turns between two frames beyond what Skate 3's own bone does (degrees): a
          flipped knee or elbow shows here
  bones   GTA's bones keep their lengths (by construction; printed as a check on the solver, mm)

usage: python retarget_fit.py [clip ...]
exit code 1 when the fitted retarget misses a limit, or when the control does NOT miss it (then the test proves nothing)
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402
import skate_fk as S  # noqa: E402

ON = ['R_IDLE_HCOM_000', 'R_IDLE_LCOM_000', 'R_IDLE_HCOM_N100', 'R_ANTIC_OLLIE_N_0_CYC', 'M_IDLE_N_0_CYC',
      'G_5050_FS_HI_0_CYC', 'OLLIE_HIGH_G', 'OLLIE_HIGH_A', 'KICKFLIP_IN_HIGH_G', 'IA_IDLE_N_N_0_CYC',
      'GR_GRAB_N_FS_0_CYC', 'GR_GRAB_N_BS_0_CYC', 'GR_NOSEGRAB_N_BS_0_CYC', 'GR_TAILGRAB_N_BS_0_CYC',
      'GR_MELON_N_BS_0_CYC', 'GR_GRAB_N_DBL_0_CYC', 'GR_MUTEGRAB_N_0_CYC', 'GR_STALEGRAB_N_0_CYC']
OFF = ['BR_STAND_0_CYC']
LIMBS = T.LEGS + T.ARMS
SRC = {'SKEL_R_Thigh': 17, 'SKEL_R_Calf': 18, 'SKEL_L_Thigh': 21, 'SKEL_L_Calf': 22,
       'SKEL_R_UpperArm': 10, 'SKEL_R_Forearm': 11, 'SKEL_L_UpperArm': 14, 'SKEL_L_Forearm': 15}
LIMITS = {'hips': 0.1, 'ankles': 0.3, 'sole': 0.5, 'hand': 2.5, 'knee': 8.0, 'pop': 12.0, 'bones': 0.1}


def angle(a, b):
    """Degrees between two rotations."""
    return math.degrees(2.0 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(a, b))))))


def measure(rt, clip, data, stance, board_y, contacts=None):
    """contacts: the (frame, hand bone) pairs to measure the hands in (the control is measured in the frames the
    fitted run found Skate 3's hand at the deck: its own deck is under feet that are somewhere else)."""
    poses = T.solve_clip(rt, clip, data, stance, board_y)
    found = set()
    rig = rt.rig
    out = dict.fromkeys(LIMITS, 0.0)
    hand_frames = 0
    before = None
    for i, pose in enumerate(poses):
        world, target = pose['world'], pose['target']
        sp = lambda sb: rt.skate_point(world, sb)
        pos = rt._positions(pose)
        hips = T.vmul(T.vadd(pos['SKEL_R_Thigh'], pos['SKEL_L_Thigh']), 0.5)
        out['hips'] = max(out['hips'], 100 * T.length(T.vsub(hips, T.vmul(T.vadd(sp(17), sp(21)), 0.5))))
        er, el = T.vsub(pos['SKEL_R_Foot'], sp(19)), T.vsub(pos['SKEL_L_Foot'], sp(23))
        out['ankles'] = max(out['ankles'], 100 * T.length(T.vsub(er, el)))
        for bone, sb in (('SKEL_R_Calf', 18), ('SKEL_L_Calf', 22)):
            out['knee'] = max(out['knee'], 100 * T.length(T.vsub(pos[bone], sp(sb))))
        inv_root = T.qconj(T.bq(world[0][0]))
        for bone, sb in (('SKEL_R_Foot', 19), ('SKEL_L_Foot', 23)):
            skate = T.qmul(T.qmul(inv_root, T.bq(world[sb][0])), T.qconj(rt.src_rest[sb]))
            gta = T.qmul(target[bone], T.qconj(rig.world_q(bone)))
            up_s, up_g = T.qrot(skate, (0, 0, 1)), T.qrot(gta, (0, 0, 1))
            out['sole'] = max(out['sole'], math.degrees(math.acos(max(-1.0, min(1.0, T.dot(up_s, up_g))))))
        for upper, lower, end, _ in LIMBS:
            for a, b in ((upper, lower), (lower, end)):
                rest = T.length(T.vsub(rig.head(a), rig.head(b)))
                out['bones'] = max(out['bones'], 1000 * abs(T.length(T.vsub(pos[a], pos[b])) - rest))
        if 'deck' in pose:
            centre, board_q = pose['deck']
            feet = T.vmul(T.vadd(er, el), 0.5)
            a = T.vadd(centre, T.vsub(sp(26), sp(25)))
            b = T.vadd(centre, T.vsub(sp(29), sp(25)))
            axis = T.norm(T.vsub(a, b))
            for bone, sb in (('SKEL_R_Hand', 12), ('SKEL_L_Hand', 16)):
                hand = sp(sb)
                t = min(max(T.dot(T.vsub(hand, b), axis), -0.2), T.length(T.vsub(a, b)) + 0.2)
                at_deck = T.length(T.vsub(hand, T.vadd(b, T.vmul(axis, t)))) < 0.19   # Skate 3's hand is at the deck
                if at_deck and contacts is None:
                    found.add((i, bone))
                if (i, bone) in (found if contacts is None else contacts):
                    hand_frames += 1
                    miss = T.vsub(T.vsub(pos[bone], hand), feet)
                    miss = T.vsub(miss, T.vmul(T.norm(T.qrot(board_q, (0, 0, 1))), rt.deck_lift if rt.fit else 0.0))
                    out['hand'] = max(out['hand'], 100 * T.length(miss))
        now = {b: (target[b], T.qmul(inv_root, T.bq(world[sb][0]))) for b, sb in SRC.items()}
        if before:
            for b in SRC:
                out['pop'] = max(out['pop'], angle(now[b][0], before[b][0]) - angle(now[b][1], before[b][1]))
        before = now
    out['hand_frames'] = hand_frames
    out['contacts'] = found
    return out


def main():
    rig = T.Rig()
    rest = S.load_clip(os.path.join(T.CSV_DIR, "RIG_TPOSE.csv"))[0]
    rest_off = S.load_clip(os.path.join(T.OFF_CSV_DIR, "RIG_TPOSE.csv"))[0]
    clips = sys.argv[1:] or ON + OFF
    off_names = set(T.load_off_meta())
    worst, contacts = {}, {}
    for label, fit in (('fitted', True), ('control (rotations only, as before 2026-10-09)', False)):
        rt, rt_off = T.Retargeter(rig, rest, fit), T.Retargeter(rig, rest_off, fit)
        stance, board_y = T.riding_stance(rt), T.riding_board_y(rt)
        print(label)
        print("  %-26s %6s %7s %6s %6s %6s %6s %6s" % ('clip', 'hips', 'ankles', 'sole', 'hand', 'knee', 'pop', 'bones'))
        total = dict.fromkeys(LIMITS, 0.0)
        for c in clips:
            off = c in off_names
            data = S.load_clip(os.path.join(T.OFF_CSV_DIR if off else T.CSV_DIR, c + ".csv"))[:240]
            m = measure(rt_off if off else rt, c, data, None if off else stance, board_y, None if fit else contacts[c])
            if fit:
                contacts[c] = m['contacts']
            hand = ("%6.1f" % m['hand']) if m['hand_frames'] else "     -"
            print("  %-26s %6.1f %7.1f %6.1f %s %6.1f %6.1f %6.2f" % (c, m['hips'], m['ankles'], m['sole'], hand, m['knee'], m['pop'], m['bones']))
            for k in LIMITS:
                total[k] = max(total[k], m[k])
        worst[fit] = total
    bad = [k for k in LIMITS if worst[True][k] > LIMITS[k]]
    blind = [k for k in ('hips', 'ankles', 'sole', 'hand') if worst[False][k] <= LIMITS[k]]
    print("limits:", LIMITS)
    print("fitted worst:", {k: round(v, 2) for k, v in worst[True].items()})
    print("control worst:", {k: round(v, 2) for k, v in worst[False].items()})
    if bad:
        print("BAD: the fitted retarget misses", bad)
    if blind:
        print("BAD: the control passes", blind, "- the check proves nothing there")
    print("RESULT:", "FAILED" if bad or blind else "ok")
    return 1 if bad or blind else 0


if __name__ == "__main__":
    sys.exit(main())
