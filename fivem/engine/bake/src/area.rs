//! GTA's collision triangles as a world for the engine: the triangles to ride, a surface for each, and the edges
//! that can be ground.
//!
//! This is SK8V's area build (`build_area_tagged` in its rust/skatev-runtime/src/world.rs, Apache-2.0) with SK8V's
//! own files doing the work: `rails` finds the lips a board can grind, `curbs` carries a ramp's toe down to the
//! ground and leaves real kerbs as they are, `plies` takes out faces that lie inside or against others,
//! `materials` says which of Skate 3's surfaces a GTA material sounds like. SK8V does this in the game, on the
//! collision it reads out of the game's memory round the player; a server cannot, so it is done here once for the
//! whole map. Everything stays in GTA's axes (z up, metres).
use crate::{curbs, grid, materials, plies, rails};
use bevy_math::Vec3;

/// The engine's mark for a triangle that wheels and bodies meet and grind probes pass through
/// (`skate_host::bridge::NO_GRIND_TAG`, from SK8V's patch 0006; the runtime checks the two are the same number).
pub const NO_GRIND_TAG: u32 = 1 << 30;

pub struct Area {
    /// Counterclockwise, each with its packed surface (and `NO_GRIND_TAG` on a ramp toe).
    pub triangles: Vec<([Vec3; 3], u32)>,
    pub rails: Vec<Vec<Vec3>>,
    pub toes: usize,
    pub dropped: usize,
}

/// `tris` each with its GTA material number.
pub fn build(tris: impl Iterator<Item = ([[f32; 3]; 3], u8)>) -> Area {
    let (gta, surfaces): (Vec<[Vec3; 3]>, Vec<u32>) = tris
        .map(|(t, material)| (t.map(Vec3::from_array), materials::surface(material).packed()))
        .filter(|(p, _)| p.iter().all(|v| v.is_finite()) && (p[1] - p[0]).cross(p[2] - p[0]).length_squared() > 1e-10)
        .unzip();
    let (found, _) = rails::find_metres(&gta);
    let grid = grid::XyGrid::triangles(curbs::CELL, &gta);
    let curbs::Bevels { triangles: toes, sources, buried, .. } = curbs::bevels_with_sources(&gta, &grid);
    // (the rails were looked for in all of it; the risers a toe covers then leave the collision)
    let mut keep = vec![true; gta.len()];
    for &i in buried
        .iter()
        .chain(&plies::interior(&gta, &grid))
        .chain(&plies::abutting_caps(&gta))
        .chain(&plies::buried_faces(&gta))
    {
        keep[i] = false;
    }
    let dropped = keep.iter().filter(|k| !**k).count();
    let triangles = gta
        .iter()
        .zip(&surfaces)
        .zip(&keep)
        .filter(|(_, k)| **k)
        .map(|((t, s), _)| (*t, *s))
        .chain(toes.iter().zip(&sources).map(|(t, &i)| (*t, surfaces[i] | NO_GRIND_TAG)))
        .collect();
    Area { triangles, rails: found, toes: toes.len(), dropped }
}
