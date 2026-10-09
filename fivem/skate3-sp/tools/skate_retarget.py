"""Retarget decoded Skate 3 clips onto a GTA V ped armature (imported with Sollumz). Runs inside Blender.

Method: both skeletons are brought into Blender axes. Each mapped GTA bone gets a reference rotation, its rest
rotation turned so that it points the way the matching Skate 3 bone points in RIG_TPOSE. For every frame, the
Skate 3 world-space change from rest (anim * rest^-1) is applied to that reference. The pelvis follows the Skate 3
pelvis position, scaled by the leg-length ratio, with the Skate 3 root bone as the origin (physics moves the ped in
game, so root motion is dropped). The feet are then pinned with IK to where the Skate 3 feet are, so they stay on
the board. The board bone's transform is exported separately for the script to place the board prop.
"""
import bpy
from mathutils import Matrix, Quaternion, Vector

import skate_fk as S

# Skate 3 bone index -> GTA bone name (side "a" is the skater's right).
MAP = {
    1: 'SKEL_Pelvis', 2: 'SKEL_Spine0', 3: 'SKEL_Spine1', 4: 'SKEL_Spine2', 5: 'SKEL_Spine3',
    6: 'SKEL_Neck_1', 7: 'SKEL_Head',
    9: 'SKEL_R_Clavicle', 10: 'SKEL_R_UpperArm', 11: 'SKEL_R_Forearm', 12: 'SKEL_R_Hand',
    13: 'SKEL_L_Clavicle', 14: 'SKEL_L_UpperArm', 15: 'SKEL_L_Forearm', 16: 'SKEL_L_Hand',
    17: 'SKEL_R_Thigh', 18: 'SKEL_R_Calf', 19: 'SKEL_R_Foot', 20: 'SKEL_R_Toe0',
    21: 'SKEL_L_Thigh', 22: 'SKEL_L_Calf', 23: 'SKEL_L_Foot', 24: 'SKEL_L_Toe0',
}
# Skate 3 child used to measure each bone's direction (end bones reuse their parent's alignment).
CHILD = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 9: 10, 10: 11, 11: 12, 13: 14, 14: 15, 15: 16,
         17: 18, 18: 19, 19: 20, 21: 22, 22: 23, 23: 24}
GTA_CHILD = {'SKEL_Pelvis': 'SKEL_Spine0', 'SKEL_Spine0': 'SKEL_Spine1', 'SKEL_Spine1': 'SKEL_Spine2',
             'SKEL_Spine2': 'SKEL_Spine3', 'SKEL_Spine3': 'SKEL_Neck_1', 'SKEL_Neck_1': 'SKEL_Head',
             'SKEL_R_Clavicle': 'SKEL_R_UpperArm', 'SKEL_R_UpperArm': 'SKEL_R_Forearm',
             'SKEL_R_Forearm': 'SKEL_R_Hand', 'SKEL_L_Clavicle': 'SKEL_L_UpperArm',
             'SKEL_L_UpperArm': 'SKEL_L_Forearm', 'SKEL_L_Forearm': 'SKEL_L_Hand',
             'SKEL_R_Thigh': 'SKEL_R_Calf', 'SKEL_R_Calf': 'SKEL_R_Foot', 'SKEL_R_Foot': 'SKEL_R_Toe0',
             'SKEL_L_Thigh': 'SKEL_L_Calf', 'SKEL_L_Calf': 'SKEL_L_Foot', 'SKEL_L_Foot': 'SKEL_L_Toe0'}
ORDER = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]

_C = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))  # Skate Y-up -> Blender Z-up
_Ci = _C.inverted()


def bq(q):
    """Skate quaternion (x,y,z,w) in Y-up -> Blender Quaternion in Z-up."""
    m = Quaternion((q[3], q[0], q[1], q[2])).to_matrix()
    return (_C @ m @ _Ci).to_quaternion()


def bv(v):
    return Vector(S.to_blender(v))


def _frame(up, side):
    """Rotation whose Z axis is `up` and X axis is `side` (orthogonalised)."""
    z = up.normalized()
    y = z.cross(side).normalized()
    x = y.cross(z)
    return Matrix((x, y, z)).transposed().to_quaternion()


def leg_length_gta(arm):
    b = arm.data.bones
    return (b['SKEL_R_Thigh'].head_local - b['SKEL_R_Calf'].head_local).length + \
           (b['SKEL_R_Calf'].head_local - b['SKEL_R_Foot'].head_local).length


def leg_length_skate(rest_world):
    p = [bv(rest_world[i][1]) for i in (17, 18, 19)]
    return (p[0] - p[1]).length + (p[1] - p[2]).length


class Retargeter:
    def __init__(self, arm, rest):
        self.arm, self.rest = arm, rest
        self.rest_world = S.fk(None, rest)
        self.scale = leg_length_gta(arm) / leg_length_skate(self.rest_world)
        bones = arm.data.bones
        self.gta_rest = {n: bones[n].matrix_local.to_quaternion() for n in MAP.values()}
        self.ref = {}
        self._align = {}
        for sb in ORDER:
            gn = MAP[sb]
            if sb == 1:
                # The pelvis bone is too short to measure; align it from two directions instead:
                # up the spine (pelvis -> chest) and across the hips (right thigh -> left thigh).
                rw = self.rest_world
                s_up = bv(rw[5][1]) - bv(rw[1][1])
                s_x = bv(rw[21][1]) - bv(rw[17][1])
                g_up = bones['SKEL_Spine3'].head_local - bones['SKEL_Pelvis'].head_local
                g_x = bones['SKEL_L_Thigh'].head_local - bones['SKEL_R_Thigh'].head_local
                align = _frame(s_up, s_x) @ _frame(g_up, g_x).inverted()
            elif sb in CHILD:
                ds = bv(self.rest_world[CHILD[sb]][1]) - bv(self.rest_world[sb][1])
                dg = bones[GTA_CHILD[gn]].head_local - bones[gn].head_local
                align = dg.rotation_difference(ds)
            else:
                align = self._align[S.PARENTS[sb]]
            self._align[sb] = align
            self.ref[gn] = align @ self.gta_rest[gn]
        self.src_rest_rot = {sb: bq(self.rest_world[sb][0]) for sb in ORDER}

    def pose_frame(self, frame):
        """Set the armature's pose for one decoded Skate 3 frame. Returns Skate world (root-relative)."""
        world = S.fk(frame, self.rest)
        root_q, root_t = bq(world[0][0]), bv(world[0][1])
        inv_root = root_q.inverted()
        pose = self.arm.pose.bones
        for pb in pose:  # start every frame from the rest pose so nothing carries over
            pb.location = (0, 0, 0)
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        # Whole body follows the Skate 3 pelvis: GTA hangs both the pelvis and the spine off SKEL_ROOT.
        target = self.skate_point(world, 1)
        rest_pelvis = self.arm.data.bones['SKEL_Pelvis'].head_local
        root_pb = pose['SKEL_ROOT']
        root_pb.matrix = Matrix.LocRotScale(self.arm.data.bones['SKEL_ROOT'].head_local + (target - rest_pelvis),
                                            self.arm.data.bones['SKEL_ROOT'].matrix_local.to_quaternion(), None)
        bpy.context.view_layer.update()
        for sb in ORDER:
            gn = MAP[sb]
            src = inv_root @ bq(world[sb][0])
            delta = src @ self.src_rest_rot[sb].inverted()
            rot = delta @ self.ref[gn]
            pb = pose[gn]
            pb.matrix = Matrix.LocRotScale(pb.matrix.to_translation(), rot, None)
            bpy.context.view_layer.update()
        return world

    def ground_z(self):
        """GTA armature-space height of the ground (the ped's feet in rest pose)."""
        b = self.arm.data.bones
        return min(b['SKEL_L_Toe0'].head_local.z, b['SKEL_L_Foot'].head_local.z) - 0.02

    def skate_point(self, world, sb):
        """A Skate 3 joint position in GTA armature space (root-relative, scaled)."""
        root_q, root_t = bq(world[0][0]), bv(world[0][1])
        p = root_q.inverted() @ (bv(world[sb][1]) - root_t)
        return p * self.scale + Vector((0, 0, self.ground_z()))
