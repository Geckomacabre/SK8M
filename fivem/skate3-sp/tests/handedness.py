"""Which side of the Skate 3 skeleton is the skater's RIGHT? (side "a" = bones 9-12 / 17-20, side "b" = 13-16 / 21-24)

Skate 3 names its one-handed gestures by hand (B_GSTR_<name>_RIGHT_* / _LEFT_*). In a _RIGHT clip the right hand
is the one that moves away from its resting place, so the hand that moves most tells us which side is right.
Then the riding pose tells us which foot leads, i.e. whether the clips as converted (side a -> GTA right) ride
regular (left foot forward) or goofy.

usage: python handedness.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import s3_to_ycd as T  # noqa: E402
import skate_fk as S  # noqa: E402

HAND = {'a': 12, 'b': 16}


def hand_travel(clip):
    data = S.load_clip(os.path.join(T.CSV_DIR, clip + ".csv"))
    rest = S.load_clip(os.path.join(T.CSV_DIR, "R_IDLE_HCOM_000.csv"))[0]
    rest_rel = {}
    out = {}
    for side, b in HAND.items():
        # hand position relative to the chest (bone 5), so body motion doesn't count
        def rel(frame):
            w = S.fk(frame, T_REST)
            return tuple(x - y for x, y in zip(w[b][1], w[5][1]))
        r0 = rel(rest)
        out[side] = max(math.dist(rel(fr), r0) for fr in data)
    return out


T_REST = S.load_clip(os.path.join(T.CSV_DIR, "RIG_TPOSE.csv"))[0]


def main():
    votes = {'a': 0, 'b': 0}
    for name in ('WAVE', 'POINT_SKY', 'PEACE', 'SHAKA', 'BICEPFLEX', 'CHECKTIME', 'THMB_DWN', 'FINGERWAG'):
        for hand in ('RIGHT', 'LEFT'):
            clip = f'B_GSTR_{name}_{hand}_CYC'
            if not os.path.exists(os.path.join(T.CSV_DIR, clip + '.csv')):
                continue
            t = hand_travel(clip)
            moved = 'a' if t['a'] > t['b'] else 'b'
            if hand == 'RIGHT':
                votes[moved] += 1
            else:
                votes['b' if moved == 'a' else 'a'] += 1
            print(f"{clip:30s} hand a moves {t['a']:.2f} m, hand b {t['b']:.2f} m -> moving hand is side {moved}")
    right = max(votes, key=votes.get)
    print(f"votes for the skater's right hand: side a {votes['a']}, side b {votes['b']} -> RIGHT = side {right}")

    rig = T.Rig()
    rt = T.Retargeter(rig, T_REST)
    st = T.riding_stance(rt)
    lead_gta = 'R' if st['R'][1] > st['L'][1] else 'L'  # converter: side a -> GTA R
    lead_side = 'a' if lead_gta == 'R' else 'b'
    lead = 'right' if lead_side == right else 'left'
    print(f"riding pose: the leading foot (front, +y) is GTA {lead_gta} = Skate 3 side {lead_side} = the skater's "
          f"{lead} foot -> the clips as converted ride {'GOOFY' if lead == 'right' else 'REGULAR'}"
          f"{'' if right == 'a' else ' (and the converter maps side a to GTA RIGHT, so left and right are swapped)'}")


if __name__ == "__main__":
    main()
