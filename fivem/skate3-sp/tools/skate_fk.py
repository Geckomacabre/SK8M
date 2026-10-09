"""Forward kinematics for decoded Skate 3 animation CSVs (AnimTest output), usable inside or outside Blender.

The Skate 3 on-board skeleton has 36 bones (parents below). Clips only carry translation channels for a few
bones; every other bone's translation comes from the RIG_TPOSE rest pose.
Skate 3 is Y-up; to_blender() maps it to Blender's Z-up.
"""
import csv
import math

PARENTS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 5, 9, 10, 11, 5, 13, 14, 15, 1, 17, 18, 19, 1, 21, 22, 23,
           0, 25, 26, 26, 25, 29, 29, 25, 25, 25, 25]

# Our names for the Skate 3 bones (by position in the hierarchy; Skate 3 stores only hashes).
NAMES = ['root', 'pelvis', 'spine0', 'spine1', 'spine2', 'chest', 'neck', 'head', 'head_end',
         'arm_a_clav', 'arm_a_upper', 'arm_a_fore', 'arm_a_hand',
         'arm_b_clav', 'arm_b_upper', 'arm_b_fore', 'arm_b_hand',
         'leg_a_thigh', 'leg_a_calf', 'leg_a_foot', 'leg_a_toe',
         'leg_b_thigh', 'leg_b_calf', 'leg_b_foot', 'leg_b_toe',
         'board', 'truck_a', 'wheel_a1', 'wheel_a2', 'truck_b', 'wheel_b1', 'wheel_b2',
         'ik_foot_a', 'ik_foot_b', 'ik_hand_a', 'ik_hand_b']


def load_clip(path):
    """Returns frames[f][bone] = (quat(x,y,z,w), trans(x,y,z)).

    The quaternions are normalised here. Skate 3 stores them lossily (their length comes out within about 1% of 1)
    and everything downstream rotates bone offsets with them: a quaternion of length 1.01 also SCALES what it
    rotates by 2%, which put the baked feet / board positions up to 3 cm away from where the game draws the feet
    (found by tests/ycd_roundtrip.py)."""
    frames = {}
    with open(path) as h:
        for r in csv.DictReader(h):
            f, b = int(r['frame']), int(r['bone'])
            q = tuple(float(r[k]) for k in ('qx', 'qy', 'qz', 'qw'))
            length = math.sqrt(sum(c * c for c in q)) or 1.0
            q = tuple(c / length for c in q)
            t = tuple(float(r[k]) for k in ('tx', 'ty', 'tz'))
            frames.setdefault(f, {})[b] = (q, t)
    return [frames[f] for f in sorted(frames)]


def animated_trans_bones(clip):
    """Bones whose translation is present in the clip (non-zero in at least one frame)."""
    return {b for fr in clip for b, (q, t) in fr.items() if any(abs(v) > 1e-6 for v in t)}


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qrot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    # v' = q v q*
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def local_pose(frame, rest, b, order='post'):
    """Clips store offsets from RIG_TPOSE: rotation composed with the rest rotation, translation added."""
    rq, rt = rest[b]
    dq, dt = frame[b]
    q = qmul(rq, dq) if order == 'post' else qmul(dq, rq)
    return q, (rt[0] + dt[0], rt[1] + dt[1], rt[2] + dt[2])


def fk(frame, rest, anim_t=None, order='post'):
    """World (quat, pos) per bone for one frame. rest = load_clip(RIG_TPOSE)[0]; frame=None gives the rest pose."""
    world = [None] * len(PARENTS)
    for b, p in enumerate(PARENTS):
        if frame is None:
            q, t = rest[b]
        else:
            q, t = local_pose(frame, rest, b, order)
        if p < 0:
            world[b] = (q, t)
        else:
            pq, pt = world[p]
            rt = qrot(pq, t)
            world[b] = (qmul(pq, q), (pt[0] + rt[0], pt[1] + rt[1], pt[2] + rt[2]))
    return world


def to_blender(v):
    """Skate 3 Y-up -> Blender Z-up."""
    return (v[0], -v[2], v[1])
