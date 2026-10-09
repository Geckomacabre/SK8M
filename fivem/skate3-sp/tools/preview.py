"""Blender helper: draw the retargeted GTA skeleton and the Skate 3 source skeleton side by side for a few frames."""
import bpy

import skate_fk as S
import skate_retarget as R


def _mat(name, rgba):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = rgba
    return m


def clear_curves():
    for ob in list(bpy.data.objects):
        if ob.type == 'CURVE':
            bpy.data.objects.remove(ob, do_unlink=True)


def draw(rt, clip, frames, spacing=1.3, rotz_view=False):
    m_r, m_l = _mat('gta_r', (0.9, 0.9, 0.9, 1)), _mat('gta_l', (0.2, 0.5, 1, 1))
    m_src, m_board = _mat('src', (1, 0.55, 0.1, 1)), _mat('board', (0.8, 0.15, 0.1, 1))
    clear_curves()
    keys = set(R.MAP.values())
    for i, f in enumerate(frames):
        world = rt.pose_frame(clip[f])
        ox = i * spacing
        cu = bpy.data.curves.new('gta_%d' % f, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = 0.022
        for m in (m_r, m_l, m_src, m_board):
            cu.materials.append(m)
        pb = rt.arm.pose.bones
        for n in keys:
            b = pb[n]
            par = b.parent if (b.parent and b.parent.name in keys) else (pb['SKEL_Pelvis'] if n != 'SKEL_Pelvis' else None)
            if par is None:
                continue
            sp = cu.splines.new('POLY'); sp.points.add(1)
            for j, v in enumerate((par.head, b.head)):
                sp.points[j].co = (v.x + ox, v.y, v.z, 1)
            sp.material_index = 1 if '_L_' in n else 0
        cs = bpy.data.curves.new('src_%d' % f, 'CURVE'); cs.dimensions = '3D'; cs.bevel_depth = 0.008
        cs.materials.append(m_src); cs.materials.append(m_board)
        for b, p in enumerate(S.PARENTS):
            if p <= 0 or b >= 32:
                continue
            sp = cs.splines.new('POLY'); sp.points.add(1)
            for j, bb in enumerate((p, b)):
                v = rt.skate_point(world, bb)
                sp.points[j].co = (v.x + ox, v.y, v.z, 1)
            sp.material_index = 1 if b >= 25 else 0
        for c in (cu, cs):
            bpy.context.collection.objects.link(bpy.data.objects.new(c.name, c))
