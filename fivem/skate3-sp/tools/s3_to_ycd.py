"""Convert decoded Skate 3 clips (AnimTest CSVs from YOUR copy of the game) into a GTA V clip dictionary.

Pure Python port of skate_retarget.Retargeter (same maths, no Blender needed), plus a CodeWalker YCD XML writer.
Output stays on your machine: the .ycd.xml is compiled with CodeWalker and used locally.

usage: python s3_to_ycd.py <dict_name> <out_dir> CLIP [CLIP ...]
       (clip names as in OnBoard.abin, e.g. OLLIE_HIGH_G OLLIE_HIGH_A)
writes <out_dir>/<dict_name>.ycd.xml and <out_dir>/<dict_name>_board.lua (board + feet track per clip)

Feet track: Skate 3 keeps the feet on the board and moves the BODY (a crouch lowers the root, a lean shifts it
sideways), so the clips have the feet floating away from the root. For every frame we export where the deck has
to be under the retargeted GTA feet ("anchor"); the player script puts that point on the ground contact point.
"""
import csv
import json
import math
import os
import sys

import skate_fk as S

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
CSV_DIR = paths.work(r"onboard_csv")
META = paths.work(r"onboard_meta.csv")
# Skate 3's OFF-board bank (OffBoard.abin, decoded by skate3-extract\tools\decode_offboard.py): standing, walking and
# running with the board in the hand, getting off and on. Same skeleton, its own rest pose.
OFF_CSV_DIR = paths.work(r"offboard_csv")
OFF_META = paths.work(r"offboard_meta.csv")
GRIP_CLIP = 'BR_STAND_0_CYC'   # the clip whose first frame says how the board sits in the hand
BOARD_BONE_TO_DECK = 0.0122   # metres from the board bone up to the top of the deck (measured on Skate 3's board model)
RIG = os.path.join(HERE, "gta_ped_rig.json")

MAP = {
    1: 'SKEL_Pelvis', 2: 'SKEL_Spine0', 3: 'SKEL_Spine1', 4: 'SKEL_Spine2', 5: 'SKEL_Spine3',
    6: 'SKEL_Neck_1', 7: 'SKEL_Head',
    9: 'SKEL_R_Clavicle', 10: 'SKEL_R_UpperArm', 11: 'SKEL_R_Forearm', 12: 'SKEL_R_Hand',
    13: 'SKEL_L_Clavicle', 14: 'SKEL_L_UpperArm', 15: 'SKEL_L_Forearm', 16: 'SKEL_L_Hand',
    17: 'SKEL_R_Thigh', 18: 'SKEL_R_Calf', 19: 'SKEL_R_Foot', 20: 'SKEL_R_Toe0',
    21: 'SKEL_L_Thigh', 22: 'SKEL_L_Calf', 23: 'SKEL_L_Foot', 24: 'SKEL_L_Toe0',
}
CHILD = {2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 9: 10, 10: 11, 11: 12, 13: 14, 14: 15, 15: 16,
         17: 18, 18: 19, 19: 20, 21: 22, 22: 23, 23: 24}
ORDER = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]

# GTA ped: how far the toe / ankle bones sit above the sole when the foot is flat (the sole plane of a standing
# ped is 1.0 m below the entity origin).
TOE_ABOVE_SOLE, ANKLE_ABOVE_SOLE = 0.042, 0.0925
FEET = ('SKEL_R_Foot', 'SKEL_R_Toe0', 'SKEL_L_Foot', 'SKEL_L_Toe0')
HANDS = ('SKEL_R_Hand', 'SKEL_L_Hand')
# Clips where one foot leaves the board (pushing, foot-drag brake, standing still with a foot on the ground).
ONE_FOOT_PREFIXES = ('R_PUSH', 'R_CRPUSH', 'R_BRAKE', 'R_STAND_IDLE', 'R_STAND_FROM', 'MONGO_PUSH')

# ------------------------------------------------------------------ quaternion / vector maths (x, y, z, w)

def qmul(a, b): return S.qmul(a, b)
def qconj(q): return (-q[0], -q[1], -q[2], q[3])
def qrot(q, v): return S.qrot(q, v)
def vadd(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def vsub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def vmul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    l = math.sqrt(dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l)
def length(a): return math.sqrt(dot(a, a))


def qnorm(q):
    l = math.sqrt(sum(c * c for c in q))
    return tuple(c / l for c in q)


def rot_between(a, b):
    """Shortest-arc rotation taking direction a to direction b."""
    a, b = norm(a), norm(b)
    d = dot(a, b)
    if d < -0.999999:
        axis = cross((1, 0, 0), a)
        if length(axis) < 1e-6:
            axis = cross((0, 1, 0), a)
        axis = norm(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    c = cross(a, b)
    return qnorm((c[0], c[1], c[2], 1.0 + d))


def mat_to_q(m):
    """3x3 rotation (rows) -> quaternion."""
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        q = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        q = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        q = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
    return qnorm(q)


def frame_q(up, side):
    z = norm(up)
    y = norm(cross(z, side))
    x = cross(y, z)
    return mat_to_q(((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2])))


# ------------------------------------------------------------------ fitting GTA's body onto Skate 3's
# The method is SK8V's (rust/skatev-runtime/src/ped.rs, Apache-2.0, by becaring; see NOTICE): the two skeletons have
# their joints at different places in the body, so wearing Skate 3's rotations alone leaves the feet and hands
# centimetres from where Skate 3 has them. GTA keeps its own bone lengths, and
#   - the pelvis goes where GTA's hip joints straddle Skate 3's (GTA's pelvis joint is 7 cm above its hips, Skate 3's
#     is between them),
#   - the feet are fitted about the vertical only (both rest poses stand flat, but the ankle-to-toe bones slope 18 and
#     29 degrees: lining those up tipped every sole 11 degrees into the deck),
#   - a two-bone solve puts each ankle on Skate 3's, bending in the plane the leg bends in,
#   - a hand goes onto Skate 3's only while it touches something (the deck, the ground): a free arm keeps Skate 3's
#     angles, because GTA's shoulders are elsewhere and pinning a free hand straightens the elbow.
# (limb: upper bone, lower bone, end bone, the Skate 3 joint the end goes to)
LEGS = (('SKEL_R_Thigh', 'SKEL_R_Calf', 'SKEL_R_Foot', 19), ('SKEL_L_Thigh', 'SKEL_L_Calf', 'SKEL_L_Foot', 23))
ARMS = (('SKEL_R_UpperArm', 'SKEL_R_Forearm', 'SKEL_R_Hand', 12), ('SKEL_L_UpperArm', 'SKEL_L_Forearm', 'SKEL_L_Hand', 16))
GROUND_FIT = (19, 23)                       # Skate 3's ankles: fitted about the vertical only
BODY = (1, 5, 7, 18, 22, 19, 23, 20, 24)    # hips, chest, head, knees, ankles, toes: the lowest one is "the ground"
TRUCKS = (26, 29)                           # Skate 3's truck joints: the line of the deck
DECK_HALF_WIDTH = 0.11
CLAVICLE_DIP = math.radians(25.0)


def _frame_m(u, v):
    """The three axes of a square frame with u first and v (made square to it) second; None when there is none."""
    lu = length(u)
    if lu < 1e-9:
        return None
    u = vmul(u, 1.0 / lu)
    w = cross(u, v)
    lw = length(w)
    if lw < 1e-9:
        return None
    w = vmul(w, 1.0 / lw)
    return u, cross(w, u), w


def _axes_q(c):
    return mat_to_q(((c[0][0], c[1][0], c[2][0]), (c[0][1], c[1][1], c[2][1]), (c[0][2], c[1][2], c[2][2])))


def _turn(a, b, hinge):
    """The rotation that takes direction a to direction b and keeps the hinge (so the bone's twist stays as it is)."""
    fa, fb = _frame_m(a, hinge), _frame_m(b, hinge)
    if not fa or not fb:
        return None
    return qnorm(qmul(_axes_q(fb), qconj(_axes_q(fa))))


def solve_limb(hip, knee, ankle, goal, hinge):
    """Two bones of fixed length from `hip`, their end put on `goal` (or as near as they reach), bending about
    `hinge`. Returns the turns of the upper and the lower bone, or None."""
    a, b = length(vsub(knee, hip)), length(vsub(ankle, knee))
    reach = vsub(goal, hip)
    dist = length(reach)
    if min(a, b, dist) < 1e-6:
        return None
    u = vmul(reach, 1.0 / dist)
    d = min(max(dist, abs(a - b) + 1e-5), a + b - 1e-5)
    along = (a * a - b * b + d * d) / (2.0 * d)
    height = math.sqrt(max(a * a - along * along, 0.0))
    side = cross(u, hinge)
    if length(side) < 1e-9:
        return None
    side = norm(side)
    new_knee = vadd(hip, vadd(vmul(u, along), vmul(side, height)))
    end = vadd(hip, vmul(u, d))
    upper = _turn(vsub(knee, hip), vsub(new_knee, hip), hinge)
    lower = _turn(vsub(ankle, knee), vsub(end, new_knee), hinge)
    if not upper or not lower:
        return None
    return upper, lower


def _fade(d, near, far):
    return 1.0 - min(1.0, max(0.0, (d - near) / (far - near)))


_C = (math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4))  # +90 deg about X: Skate Y-up -> Blender Z-up


def bq(q): return qmul(qmul(_C, q), qconj(_C))


# Mirroring left <-> right (for the goofy stance): reflect across the plane the board rolls in (x = 0).
MIRROR_SUFFIX = '_MIR'
def mirror_q(q): return (q[0], -q[1], -q[2], q[3])
def mirror_v(v): return (-v[0], v[1], v[2])


def other_side(bone):
    if bone.startswith('SKEL_L_'):
        return 'SKEL_R_' + bone[7:]
    if bone.startswith('SKEL_R_'):
        return 'SKEL_L_' + bone[7:]
    return bone
def bv(v): return S.to_blender(v)

# ------------------------------------------------------------------ retarget


class Rig:
    def __init__(self, path=RIG):
        data = json.load(open(path))["bones"]
        self.bones = {b["name"]: b for b in data}
        self.order = [b["name"] for b in data]  # parents always precede children in the GTA skeleton
        # bone offset from its parent, in the parent's rest frame (for forward kinematics)
        self.offset = {}
        for b in data:
            if b["parent"] is not None:
                par = self.bones[b["parent"]]
                self.offset[b["name"]] = qrot(qconj(tuple(par["world_q"])), vsub(tuple(b["head"]), tuple(par["head"])))
        self.chain = set()  # bones whose world position we need: the feet, the hands and their ancestors
        for n in FEET + HANDS:
            while n is not None:
                self.chain.add(n)
                n = self.bones[n]["parent"]

    def head(self, n): return tuple(self.bones[n]["head"])
    def world_q(self, n): return tuple(self.bones[n]["world_q"])


class Retargeter:
    def __init__(self, rig, rest, fit=True):
        """fit = False is the retarget as it was until 2026-10-09 (rotations only, the pelvis on Skate 3's pelvis):
        kept for the tests' controls."""
        self.rig, self.rest, self.fit = rig, rest, fit
        rw = self.rest_world = S.fk(None, rest)
        P = lambda sb: bv(rw[sb][1])
        g = rig.head
        leg_g = length(vsub(g('SKEL_R_Thigh'), g('SKEL_R_Calf'))) + length(vsub(g('SKEL_R_Calf'), g('SKEL_R_Foot')))
        leg_s = length(vsub(P(17), P(18))) + length(vsub(P(18), P(19)))
        self.scale = leg_g / leg_s
        self.ground = min(g('SKEL_L_Toe0')[2], g('SKEL_L_Foot')[2]) - 0.02
        gta_child = {MAP[k]: MAP[v] for k, v in CHILD.items()}
        level = lambda v: (v[0], v[1], 0.0)
        align, self.ref = {}, {}
        for sb in ORDER:
            gn = MAP[sb]
            if sb == 1:
                a = qmul(frame_q(vsub(P(5), P(1)), vsub(P(21), P(17))),
                         qconj(frame_q(vsub(g('SKEL_Spine3'), g('SKEL_Pelvis')), vsub(g('SKEL_L_Thigh'), g('SKEL_R_Thigh')))))
            elif fit and sb in GROUND_FIT:
                a = rot_between(level(vsub(g(gta_child[gn]), g(gn))), level(vsub(P(CHILD[sb]), P(sb))))
            elif sb in CHILD:
                a = rot_between(vsub(g(gta_child[gn]), g(gn)), vsub(P(CHILD[sb]), P(sb)))
            else:
                a = align[S.PARENTS[sb]]
            align[sb] = a
            self.ref[gn] = qmul(a, rig.world_q(gn))
        self.src_rest = {sb: bq(rw[sb][0]) for sb in ORDER}
        # the middle of GTA's hip joints, in the pelvis bone's own frame
        self.hips = vmul(vadd(rig.offset['SKEL_R_Thigh'], rig.offset['SKEL_L_Thigh']), 0.5)
        # each limb's hinge (the axis its rest pose bends about), in its upper bone's own frame
        self.hinge = {}
        for upper, lower, end, _ in LEGS + ARMS:
            axis = cross(vsub(g(lower), g(upper)), vsub(g(end), g(lower)))
            axis = norm(axis) if length(axis) > 1e-9 else qrot(rig.world_q(upper), (0.0, 0.0, 1.0))
            self.hinge[upper] = qrot(qconj(rig.world_q(upper)), axis)
        # our deck is put under GTA's soles, Skate 3's is under its own: GTA's ankle is this much nearer its sole,
        # so a hand on the deck is that much higher over Skate 3's ankles than Skate 3 has it
        self.deck_lift = P(19)[2] * self.scale - ANKLE_ABOVE_SOLE

    def skate_point(self, world, sb):
        rq, rt = bq(world[0][0]), bv(world[0][1])
        p = qrot(qconj(rq), vsub(bv(world[sb][1]), rt))
        return vadd(vmul(p, self.scale), (0, 0, self.ground))

    def _limb(self, pose, pos, limb, goal):
        """Put the end of a limb on `goal`: new rotations for its upper and lower bone in pose['target']."""
        upper, lower, end, _ = limb
        target = pose['target']
        hip, knee, ankle = pos[upper], pos[lower], pos[end]
        # the limb's own hinge; as it straightens (about 1 to 6 degrees of bend) the hinge its rest pose has, carried
        # by the upper bone, takes over, and the limb's own is kept on that side: the bend never flips between frames
        rest_hinge = norm(qrot(target[upper], self.hinge[upper]))
        chain = cross(vsub(knee, hip), vsub(ankle, knee))
        if dot(chain, rest_hinge) < 0:
            chain = vmul(chain, -1.0)
        bent = length(chain) / max(length(vsub(knee, hip)) * length(vsub(ankle, knee)), 1e-9)
        w = min(1.0, max(0.0, (bent - 0.02) / 0.08))
        hinge = rest_hinge
        if w > 0:
            mixed = vadd(vmul(rest_hinge, 1.0 - w), vmul(norm(chain), w))
            hinge = norm(mixed) if length(mixed) > 1e-9 else rest_hinge
        turns = solve_limb(hip, knee, ankle, goal, hinge)
        if turns:
            target[upper] = qnorm(qmul(turns[0], target[upper]))
            target[lower] = qnorm(qmul(turns[1], target[lower]))

    def _positions(self, pose):
        """Where the feet, the hands and the joints above them are (armature space), for the pose as it stands."""
        rig, target = self.rig, pose['target']
        wq, pos = {}, {}
        for n in rig.order:
            b = rig.bones[n]
            if b["parent"] is None:
                wq[n], pos[n] = rig.world_q(n), pose['root']
                continue
            pw = wq[b["parent"]]
            wq[n] = target[n] if n in target else qmul(pw, tuple(b["local_q"]))
            if n in rig.chain:
                pos[n] = vadd(pos[b["parent"]], qrot(pw, rig.offset[n]))
        return pos

    def solve(self, frame):
        """One decoded Skate 3 frame as a pose of the GTA skeleton (not mirrored): the bones' rotations, the root's
        place, and the legs already on Skate 3's ankles. `reach` then does the arms, `emit` writes it out."""
        world = S.fk(frame, self.rest)
        inv_root = qconj(bq(world[0][0]))
        target = {}
        for sb in ORDER:
            src = qmul(inv_root, bq(world[sb][0]))
            target[MAP[sb]] = qmul(qmul(src, qconj(self.src_rest[sb])), self.ref[MAP[sb]])
        rig = self.rig
        sp = lambda sb: self.skate_point(world, sb)
        pose = {'world': world, 'target': target,
                'board': (sp(25), qnorm(qmul(inv_root, bq(world[25][0]))))}
        if not self.fit:
            pose['root'] = vadd(rig.head('SKEL_ROOT'), vsub(sp(1), rig.head('SKEL_Pelvis')))
            return pose
        hips = vmul(vadd(sp(17), sp(21)), 0.5)
        pose['root'] = vsub(hips, qrot(target['SKEL_Pelvis'], self.hips))
        pos = self._positions(pose)
        for limb in LEGS:
            self._limb(pose, pos, limb, sp(limb[3]))
        return pose

    def reach(self, pose, deck=None):
        """The arms. deck = (the middle of the deck's top, the board's rotation) where the board is under this pose's
        feet (armature space, not mirrored), or None for a clip without a board under the feet. A hand near the deck
        or down at the level of the lowest part of the body is touching something and goes where Skate 3's hand is;
        the weight fades over a band, so the arm never snaps."""
        if not self.fit:
            return pose
        world, target = pose['world'], pose['target']
        sp = lambda sb: self.skate_point(world, sb)
        lowest = min(sp(sb)[2] for sb in BODY)
        line = up = None
        if deck:
            centre, board_q = deck
            origin = vsub(vsub(centre, qrot(board_q, (0.0, 0.0, BOARD_BONE_TO_DECK * self.scale))), sp(25))
            line = (vadd(origin, sp(TRUCKS[0])), vadd(origin, sp(TRUCKS[1])))
            up = norm(qrot(board_q, (0.0, 0.0, 1.0)))

        def touching(hand):
            on_board = 0.0
            if line:
                a, b = line
                axis = norm(vsub(a, b))
                t = min(max(dot(vsub(hand, b), axis), -0.2), length(vsub(a, b)) + 0.2)
                on_board = _fade(length(vsub(hand, vadd(b, vmul(axis, t)))) - DECK_HALF_WIDTH, 0.08, 0.2)
            return max(on_board, _fade(hand[2] - lowest, 0.15, 0.35)), on_board

        goals = []
        for limb in ARMS:
            goal = sp(limb[3])
            w, on_board = touching(goal)
            if up and on_board > 0:
                goal = vadd(goal, vmul(up, self.deck_lift * on_board))
            goals.append((goal, w))
        # a hand that touches something further off than GTA's arm reaches (its shoulder is higher than Skate 3's)
        # dips the collar bone towards it, 25 degrees at most, rather than locking the elbow straight
        pos = self._positions(pose)
        for (upper, lower, end, _), (goal, w) in zip(ARMS, goals):
            clavicle = self.rig.bones[upper]["parent"]
            full = length(vsub(pos[upper], pos[lower])) + length(vsub(pos[lower], pos[end]))
            excess = (length(vsub(goal, pos[upper])) - 0.98 * full) * w
            arm = vsub(pos[upper], pos[clavicle])
            axis = cross(arm, vsub(goal, pos[clavicle]))
            if excess > 0 and length(arm) > 1e-3 and length(axis) > 1e-9:
                half = min(excess / length(arm), CLAVICLE_DIP) / 2.0
                axis = vmul(norm(axis), math.sin(half))
                target[clavicle] = qnorm(qmul((axis[0], axis[1], axis[2], math.cos(half)), target[clavicle]))
        pos = self._positions(pose)
        for limb, (goal, w) in zip(ARMS, goals):
            if w > 0:
                wrist = pos[limb[2]]
                self._limb(pose, pos, limb, vadd(wrist, vmul(vsub(goal, wrist), w)))
        return pose

    def frame(self, frame, mirror=False):
        """solve + emit, the arms as Skate 3's rotations leave them (see reach)."""
        return self.emit(self.solve(frame), mirror)

    def emit(self, pose, mirror=False):
        """Returns (root_pos, {bone: local quat}, board (pos, quat), feet positions, hands) in GTA armature space."""
        rig = self.rig
        target, root_pos, board = pose['target'], pose['root'], pose['board']
        if mirror:
            # each bone takes the reflected change-from-rest of the bone on the other side
            target = {n: qmul(mirror_q(qmul(target[other_side(n)], qconj(rig.world_q(other_side(n))))),
                              rig.world_q(n)) for n in target}
            root_pos = vadd(rig.head('SKEL_ROOT'), mirror_v(vsub(root_pos, rig.head('SKEL_ROOT'))))
            board = (mirror_v(board[0]), mirror_q(board[1]))
        wq, local, pos = {}, {}, {}
        for n in rig.order:
            b = rig.bones[n]
            if b["parent"] is None:
                wq[n] = rig.world_q(n)
                pos[n] = root_pos
                continue
            pw = wq[b["parent"]]
            if n in target:
                wq[n] = target[n]
                local[n] = qnorm(qmul(qconj(pw), target[n]))
            else:
                wq[n] = qmul(pw, tuple(b["local_q"]))
            if n in rig.chain:
                pos[n] = vadd(pos[b["parent"]], qrot(pw, rig.offset[n]))
        return root_pos, local, board, {n: pos[n] for n in FEET}, {n: (pos[n], wq[n]) for n in HANDS}

# ------------------------------------------------------------------ YCD XML


def _f(v): return repr(float(v)) if abs(v) >= 1e-9 else "0"


def channel_xml(values, ind):
    lo, hi = min(values), max(values)
    pad = " " * ind
    if hi - lo < 1e-6:
        return (f'{pad}<Item>\n{pad} <Type value="StaticFloat" />\n{pad} <Value value="{_f(values[0])}" />\n'
                f'{pad}</Item>\n')
    quantum = max((hi - lo) / 65535.0, 1e-7)
    vals = " ".join(_f(v) for v in values)
    return (f'{pad}<Item>\n{pad} <Type value="QuantizeFloat" />\n{pad} <Quantum value="{_f(quantum)}" />\n'
            f'{pad} <Offset value="{_f(lo)}" />\n{pad} <Values>{vals}</Values>\n{pad}</Item>\n')


def quat_track_xml(quats, ind):
    # GTA lerps quaternion components without a dot check, so keep consecutive frames in one hemisphere
    # (same fix as Sollumz's exporter). Written as four explicit channels, like Sollumz.
    qs = [quats[0]]
    for q in quats[1:]:
        if sum(a * b for a, b in zip(q, qs[-1])) < 0:
            q = tuple(-c for c in q)
        qs.append(q)
    return "".join(channel_xml([q[i] for q in qs], ind) for i in range(4))


def jenkins(s):
    h = 0
    for ch in s.lower().encode():
        h = (h + ch) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


# GTA ped animations put the root at ~identity, which turns the bind pose (facing -Y) to face the entity's +Y.
R180 = (0.0, 0.0, 1.0, 0.0)


def to_entity(p): return (-p[0], -p[1], p[2])


def animation_xml(name, fps, root_pos, locals_, rig):
    n = len(root_pos)
    duration = (n - 1) / fps if n > 1 else 1.0 / fps
    tracks = [(0, 0, None), (0, 1, None)] + [(rig.bones[b]["tag"], 1, b) for b in locals_[0]]
    tracks.sort(key=lambda t: (t[1], t[0]))
    sig = (jenkins(name) + 1) & 0xFFFFFFFF  # must be unique per animation (used for caching)
    out = [f'  <Item>\n   <Hash>{name}</Hash>\n   <Unknown10 value="0" />\n   <FrameCount value="{n}" />\n'
           f'   <SequenceFrameLimit value="{n + 30}" />\n   <Duration value="{_f(duration)}" />\n'
           f'   <Unknown1C>hash_{sig:08X}</Unknown1C>\n   <BoneIds>\n']
    for tag, track, _ in tracks:
        out.append(f'    <Item>\n     <BoneId value="{tag}" />\n     <Track value="{track}" />\n     <Unk0 value="{0 if track == 0 else 1}" />\n    </Item>\n')
    out.append(f'   </BoneIds>\n   <Sequences>\n    <Item>\n     <Hash>{name}_seq</Hash>\n     <FrameCount value="{n}" />\n     <SequenceData>\n')
    for tag, track, bone in tracks:
        out.append('      <Item>\n       <Channels>\n')
        if track == 0:
            ent = [to_entity(p) for p in root_pos]
            for i in range(3):
                out.append(channel_xml([p[i] for p in ent], 8))
        elif bone is None:
            root_q = qnorm(qmul(R180, rig.world_q('SKEL_ROOT')))
            out.append(quat_track_xml([root_q] * n, 8))
        else:
            out.append(quat_track_xml([fr[bone] for fr in locals_], 8))
        out.append('       </Channels>\n      </Item>\n')
    out.append('     </SequenceData>\n    </Item>\n   </Sequences>\n  </Item>\n')
    return "".join(out), duration


def clip_xml(name, duration):
    return (f'  <Item>\n   <Hash>{name}</Hash>\n   <Name>pack:/{name}.clip</Name>\n   <Type value="Animation" />\n'
            f'   <Unknown30 value="0" />\n   <Tags />\n   <Properties />\n   <AnimationHash>{name}</AnimationHash>\n'
            f'   <StartTime value="0" />\n   <EndTime value="{_f(duration)}" />\n   <Rate value="1" />\n  </Item>\n')


def load_meta():
    return {r['name']: r for r in csv.DictReader(open(META))}


def load_off_meta():
    """The off-board bank's clips that are not in the on-board bank as well (a name in both is the on-board one)."""
    if not os.path.exists(OFF_META):
        return {}
    on = load_meta()
    return {r['name']: r for r in csv.DictReader(open(OFF_META)) if r['name'] not in on}


def standing_ground(rt):
    """Where the ground is under a rider standing off the board, in the ped's own space: under the soles of the GTA
    skeleton in Skate 3's own stand (the middle value over the clip: the feet shift a little in it). The retargeted
    legs are GTA's lengths, so this is not where Skate 3's root says the ground is (it is 7 to 8 cm lower)."""
    data = S.load_clip(os.path.join(OFF_CSV_DIR, "BR_STAND_0_CYC.csv"))
    lows = sorted(min(contact(f[3], 'R')[2], contact(f[3], 'L')[2]) for f in (rt.frame(fr) for fr in data[::6]))
    return lows[len(lows) // 2]


def carry_rows(rt, rest, data, frames, ground):
    """For an off-board clip, per frame: the ground point under the rider (where the script puts the ground), the top
    of the deck in the rider's hand, and how far the rider has gone forward since the clip's first frame. All in the
    ped's own space; the forward distance is the clip's root motion, scaled like the skeleton, so that a script moving
    the ped by it keeps the feet from sliding. A clip whose root rises and comes down again (the hop of a mount) has
    that in its ground point: the ground is that much further under the rider."""
    out = []
    y0 = z0 = None
    for fr, f in zip(data, frames):
        root = S.fk(fr, rest)[0][1]
        if z0 is None:
            y0, z0 = root[1], root[2]
        pos, q = f[2]
        deck = to_entity(vadd(pos, qrot(q, (0.0, 0.0, BOARD_BONE_TO_DECK * rt.scale))))
        out.append(((0.0, 0.0, ground - (root[1] - y0) * rt.scale), deck, (root[2] - z0) * rt.scale))
    return out


def in_hand(rt, frames, mirror):
    """The board of an off-board clip against the hand that carries it (the right one as authored, the left one in
    a mirrored copy), per frame: the top of the deck and the board's rotation in that hand bone's own frame.
    Skate 3 keeps the board rigid in the hand while it is carried (within a few degrees, a few centimetres); in the
    clips that take it out of the hand (onto the ground for a mount, off the feet in a dismount) it leaves."""
    hand = 'SKEL_L_Hand' if mirror else 'SKEL_R_Hand'
    out = []
    for f in frames:
        hp, hq = f[4][hand]
        bp, bqv = f[2]
        deck = vadd(bp, qrot(bqv, (0.0, 0.0, BOARD_BONE_TO_DECK * rt.scale)))
        out.append((qrot(qconj(hq), vsub(deck, hp)), qnorm(qmul(qconj(hq), bqv))))
    return out


def carried(clip):
    """Is the board in the hand through the whole clip? Every clip with the board (BR_) except the ones that take it
    out of the hand or put it there: onto the ground for a mount, off the feet in a dismount, kicked away.
    (The clips' own board bone is not what holds the board there: against the wrist it is rigid in rotation, within
    a degree or two, but up to 30 cm off in place from clip to clip. The game plainly brings hand and board together
    itself. Here the board is fixed in the hand: see the player.)"""
    c = clip.upper()
    return c.startswith('BR_') and not any(k in c for k in ('MOUNT', 'KICKOUT'))


def contact(feet, side):
    """Point of the deck under one foot (entity space): under the ball of the foot, at the sole."""
    ankle, toe = to_entity(feet[f'SKEL_{side}_Foot']), to_entity(feet[f'SKEL_{side}_Toe0'])
    return (toe[0] * 0.7 + ankle[0] * 0.3, toe[1] * 0.7 + ankle[1] * 0.3,
            min(toe[2] - TOE_ABOVE_SOLE, ankle[2] - ANKLE_ABOVE_SOLE))


def one_foot(clip):
    """None when both feet ride the board, else the side ('R' front / 'L' back) of the foot that stays on it."""
    c = clip.upper()
    if c.startswith(ONE_FOOT_PREFIXES) or (c.startswith('PRO_') and '_PUSH_' in c):
        # mongo = pushing with the front foot; the clips that bring it back are named ..._M_... (R_PUSH_L_M_N_OUT_FRONT)
        return 'L' if ('MONGO' in c or '_M_' in c) else 'R'
    return None


def lying(clip):
    """The coffin: the rider lies back along the board and the feet leave it, past its end."""
    return '_COFFIN_' in clip.upper()


def anchors(clip, feet_frames, stance, mirror=False, board_frames=None, board_y=0.0):
    """Deck centre under the feet, per frame. stance = each foot's offset from the deck centre when riding.

    The coffin clips (see lying) are the exception along the board: there the feet slide a metre out past its end
    while the rider lies back, and a deck kept under the feet is a deck with nobody on it (seen in the game: the
    board under the boots, the body on the tarmac). The clips' own board bone does not move along the board while
    that happens, so there the deck stays where that bone has it: board_frames = the board bone per frame
    ((pos, quat), armature space), board_y = how far the deck centre under a riding rider's feet is from that bone
    along the board. Sideways and in height the feet still say where the deck is: the bone is no use for those in
    the crouched and lying clips (it is 0.4 to 0.8 m off to the side of the body in them)."""
    side = one_foot(clip)
    if mirror:
        stance = {'R': mirror_v(stance['L']), 'L': mirror_v(stance['R'])}
        side = side and ('L' if side == 'R' else 'R')
    out = []
    for feet in feet_frames:
        if side:
            out.append(vsub(contact(feet, side), stance[side]))
        else:
            out.append(vmul(vadd(contact(feet, 'R'), contact(feet, 'L')), 0.5))
    if board_frames and lying(clip):
        out = [(a[0], to_entity(b[0])[1] + board_y, a[2]) for a, b in zip(out, board_frames)]
    return out


def blend_frames(a, b, t):
    """Blend two decoded Skate 3 frames ({bone: (quat, trans)})."""
    out = {}
    for bone, (qa, ta) in a.items():
        qb, tb = b[bone]
        if sum(x * y for x, y in zip(qa, qb)) < 0:
            qb = tuple(-c for c in qb)
        out[bone] = (qnorm(tuple(x + (y - x) * t for x, y in zip(qa, qb))),
                     tuple(x + (y - x) * t for x, y in zip(ta, tb)))
    return out


def sweep(left, centre, right, steps=41):
    """A pose-space clip to scrub by phase: 0 = `left` pose, 0.5 = `centre`, 1 = `right` (first frame of each)."""
    pose = lambda c: S.load_clip(os.path.join(CSV_DIR, c + ".csv"))[0]
    l, c, r = pose(left), pose(centre), pose(right)
    frames = []
    for i in range(steps):
        u = i / (steps - 1) * 2.0
        frames.append(blend_frames(l, c, u) if u <= 1.0 else blend_frames(c, r, u - 1.0))
    return frames


# Riding blends, baked as scrub clips: lean left .. upright .. lean right (Skate 3 blends these poses live).
SWEEPS = {
    'R_LEAN_HCOM': ('R_IDLE_HCOM_N100', 'R_IDLE_HCOM_000', 'R_IDLE_HCOM_P100'),
    'R_LEAN_LCOM': ('R_IDLE_LCOM_N100', 'R_IDLE_LCOM_000', 'R_IDLE_LCOM_P100'),
    'R_LEAN_ANTIC_OLLIE': ('R_ANTIC_OLLIE_L_0_CYC', 'R_ANTIC_OLLIE_N_0_CYC', 'R_ANTIC_OLLIE_R_0_CYC'),
    'R_LEAN_ANTIC_NOLLIE': ('R_ANTIC_NOLLIE_L_0_CYC', 'R_ANTIC_NOLLIE_N_0_CYC', 'R_ANTIC_NOLLIE_R_0_CYC'),
    # the crouches with the stick held round to a side: the wind-up for shuvits (Anticipations/AnticCyc.xml)
    'R_LEAN_ANTIC_360SHUVIT': ('R_ANTIC_360SHUVIT_L_0_CYC', 'R_ANTIC_360SHUVIT_N_0_CYC', 'R_ANTIC_360SHUVIT_R_0_CYC'),
    'R_LEAN_ANTIC_FS360SHUVIT': ('R_ANTIC_FS360SHUVIT_L_0_CYC', 'R_ANTIC_FS360SHUVIT_N_0_CYC',
                                 'R_ANTIC_FS360SHUVIT_R_0_CYC'),
    'R_LEAN_ANTIC_N360SHUVIT': ('R_ANTIC_N360SHUVIT_L_0_CYC', 'R_ANTIC_N360SHUVIT_N_0_CYC',
                                'R_ANTIC_N360SHUVIT_R_0_CYC'),
    'R_LEAN_ANTIC_NFS360SHUVIT': ('R_ANTIC_NFS360SHUVIT_L_0_CYC', 'R_ANTIC_NFS360SHUVIT_N_0_CYC',
                                  'R_ANTIC_NFS360SHUVIT_R_0_CYC'),
}


# The same blends as STATIC poses: <SWEEP>_S0 (full left) .. _S4 (upright) .. _S8 (full right), two identical frames
# each. Plain looping clips sync to other players in FiveM, a scrubbed one doesn't, so the controller steps through
# these (and lets the game cross-fade between them) instead of scrubbing.
STEPS = 9


def step_names():
    return [f'{s}_S{k}' for s in SWEEPS for k in range(STEPS)]


def step_pose(name):
    """The frames of a step clip, or None if name isn't one."""
    base, _, k = name.rpartition('_S')
    if base not in SWEEPS or not k.isdigit() or int(k) >= STEPS:
        return None
    pose = sweep(*SWEEPS[base])[int(k) * 40 // (STEPS - 1)]  # sweep() has 41 frames: 0, 5, .., 40
    return [pose, pose]


def riding_stance(rt):
    """Each foot's offset from the deck centre in the plain riding pose."""
    ride = rt.frame(S.load_clip(os.path.join(CSV_DIR, "R_IDLE_HCOM_000.csv"))[0])[3]
    mid = vmul(vadd(contact(ride, 'R'), contact(ride, 'L')), 0.5)
    return {s: vsub(contact(ride, s), mid) for s in 'RL'}


def riding_board_y(rt):
    """How far along the board (entity y) the deck centre under a riding rider's feet is from the board bone."""
    ride = rt.frame(S.load_clip(os.path.join(CSV_DIR, "R_IDLE_HCOM_000.csv"))[0])
    mid = vmul(vadd(contact(ride[3], 'R'), contact(ride[3], 'L')), 0.5)
    return mid[1] - to_entity(ride[2][0])[1]


def solve_clip(rt, clip, data, stance=None, board_y=0.0):
    """Every frame of a clip as a finished pose (Retargeter.solve, then the arms). stance = riding_stance(rt) for a
    clip with the board under the feet (the deck is then where `anchors` puts it, and a hand near it is put on it;
    each pose gets it as pose['deck']); None for an off-board clip (only a hand down at the ground is)."""
    poses = [rt.solve(fr) for fr in data]
    if stance:
        plain = [rt.emit(p) for p in poses]
        decks = anchors(clip, [f[3] for f in plain], stance, False, [f[2] for f in plain], board_y)
        for p, f, a in zip(poses, plain, decks):
            p['deck'] = (to_entity(a), f[2][1])     # (to_entity is its own inverse)
            rt.reach(p, p['deck'])
    else:
        for p in poses:
            rt.reach(p)
    return poses


def pose_clip(rt, clip, data, mirror=False, stance=None, board_y=0.0):
    """Every frame of a clip as Retargeter.emit gives it, arms included (see solve_clip)."""
    return [rt.emit(p, mirror) for p in solve_clip(rt, clip, data, stance, board_y)]


def convert(dict_name, clips, out_dir):
    rig = Rig()
    rest = S.load_clip(os.path.join(CSV_DIR, "RIG_TPOSE.csv"))[0]
    rt = Retargeter(rig, rest)
    meta = load_meta()
    off_meta = load_off_meta()
    rt_off, rest_off = None, None
    stance = riding_stance(rt)
    board_y = riding_board_y(rt)
    anims, clipx, boards = [], [], []
    # off-board clips with the board in the hand throughout; where it is in the hand at the end of the ones that put
    # it there; the board in each hand
    in_hands, ends, grips = set(), {}, {}
    for full in clips:
        mirror = full.endswith(MIRROR_SUFFIX)
        c = full[:-len(MIRROR_SUFFIX)] if mirror else full
        steps = step_pose(c)
        if c in SWEEPS:
            data, fps = sweep(*SWEEPS[c]), 30.0
        elif steps:
            data, fps = steps, 30.0
        elif c in off_meta:
            if rt_off is None:
                rest_off = S.load_clip(os.path.join(OFF_CSV_DIR, "RIG_TPOSE.csv"))[0]
                rt_off = Retargeter(rig, rest_off)
                off_ground = standing_ground(rt_off)
            data = S.load_clip(os.path.join(OFF_CSV_DIR, c + ".csv"))
            fps = float(off_meta[c]['fps'])
        else:
            data = S.load_clip(os.path.join(CSV_DIR, c + ".csv"))
            fps = float(meta[c]['fps']) if c in meta else 30.0
        off = c in off_meta
        frames = pose_clip(rt_off if off else rt, c, data, mirror, None if off else stance, board_y)
        name = full.lower()
        ax, dur = animation_xml(name, fps, [f[0] for f in frames], [f[1] for f in frames], rig)
        anims.append(ax)
        clipx.append(clip_xml(name, dur))
        if off:
            boards.append((name, fps, [f[2] for f in frames], carry_rows(rt_off, rest_off, data, frames, off_ground)))
            rel = in_hand(rt_off, frames, mirror)
            if carried(c):
                in_hands.add(name)
            elif c.upper().startswith('BR_') and length(rel[-1][0]) < 0.35:
                ends[name] = rel[-1]      # (a dismount: the board ends in the hand, about so)
            if c == GRIP_CLIP:
                grips['L' if mirror else 'R'] = rel[0]
        else:
            boards.append((name, fps, [f[2] for f in frames], anchors(c, [f[3] for f in frames], stance, mirror,
                                                                 [f[2] for f in frames], board_y)))
    os.makedirs(out_dir, exist_ok=True)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<ClipDictionary>\n <Clips>\n' + "".join(clipx) +
           ' </Clips>\n <Animations>\n' + "".join(anims) + ' </Animations>\n</ClipDictionary>\n')
    xml_path = os.path.join(out_dir, dict_name + ".ycd.xml")
    open(xml_path, "w", encoding="utf-8").write(xml)
    lua = ["-- generated by s3_to_ycd.py, per frame, relative to the ped entity (x right, y forward, z up):",
           "-- {qx, qy, qz, qw, ax, ay, az} = board rotation (long axis y), then the deck centre under the feet",
           "-- off-board clips: {qx, qy, qz, qw, gx, gy, gz, bx, by, bz, d} = board rotation, the ground under the rider,",
           "-- the top of the deck in the hand, and the metres gone forward since the clip began (its root motion)",
           "SkateBoardTracks = SkateBoardTracks or {}"]
    for name, fps, frames, anch in boards:
        if anch and len(anch[0]) == 3 and isinstance(anch[0][0], tuple):   # (an off-board clip, see carry_rows)
            rows = ",".join("{%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f}" % (
                *qnorm(qmul(R180, q)), *g, *b, d) for (_, q), (g, b, d) in zip(frames, anch))
        else:
            rows = ",".join("{%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f}" % (*qnorm(qmul(R180, q)), *a)
                            for (_, q), a in zip(frames, anch))
        flag = "hand=true, " if name in in_hands else ""
        if name in ends:
            flag = "grip1={%.4f,%.4f,%.4f,%.5f,%.5f,%.5f,%.5f}, " % (*ends[name][0], *ends[name][1])
        lua.append(f'SkateBoardTracks["{dict_name}/{name}"] = {{fps={fps:g}, {flag}frames={{{rows}}}}}')
    if grips:
        lua.append("-- the board in the hand that carries it, in that hand bone's own frame: the top of the deck (x, y, z) and")
        lua.append("-- the board's rotation (qx, qy, qz, qw). R = SKEL_R_Hand (the clips as authored), L = SKEL_L_Hand (mirrored)")
        lua.append('SkateBoardGrip = rawget(_G, "SkateBoardGrip") or {}')
        for side, (p, q) in sorted(grips.items()):
            lua.append("SkateBoardGrip.%s = {%.4f,%.4f,%.4f,%.5f,%.5f,%.5f,%.5f}" % (side, *p, *q))
    open(os.path.join(out_dir, dict_name + "_board.lua"), "w").write("\n".join(lua) + "\n")
    return xml_path, rt


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    p, rt = convert(sys.argv[1], sys.argv[3:], sys.argv[2])
    print("wrote", p, "scale", round(rt.scale, 4))
