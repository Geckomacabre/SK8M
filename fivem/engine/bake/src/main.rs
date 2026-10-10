//! The map's collision made ready for the engine, once, for the whole map: world.sk8w.
//!
//!     sk8m-bake collision.svwc world.sk8w [threads]
//!
//! collision.svwc is what SK8V's skatev-world-cache writes: GTA's collision triangles with their material
//! numbers, in 64 m tiles. Before the engine can ride them SK8V finds the grind rails in them, carries ramp toes
//! down to the ground and takes out doubled faces (`area.rs`). In the game SK8V does that on another thread for
//! the 128 m round the player. A FiveM server has one thread and a build of 30 m round one rider stalls it for a
//! tenth of a second, so here it is done ahead of time: the map is worked through in blocks of 128 m, each with
//! 16 m of its neighbours round it so that an edge at a block's border is judged with what lies beyond it, and a
//! triangle or a piece of rail is kept by the block its middle is in.
//!
//! The file (all values little-endian, GTA's axes, z up, metres):
//!
//! ```text
//! 4 bytes  "SK8W"
//! u32      version = 1
//! f32      tile size (metres, XY)
//! u32      tile count
//! repeat tile count (sorted by tx, ty):
//!   i32 tx, i32 ty, u64 where the tile's block starts in the file, u32 its packed bytes, u32 its bytes unpacked,
//!   u32 its triangle count
//! then each tile's block, packed with zlib:
//!   repeat triangle count: 9 * f32 corners a, b, c (x, y, z), u32 surface tag
//!   then rails until the block ends: u32 the rail's number, u32 point count, the points (3 * f32 each)
//! ```
//!
//! A triangle is in every tile its XY box overlaps and a rail, whole, in every tile it passes through, so that a
//! reader takes the tiles round a place and has everything that reaches into them; it drops the repeats (a
//! triangle by the tile its box starts in, a rail by its number).
#[allow(dead_code)]
#[path = "../../overlay/sk8v/curbs.rs"]
mod curbs;
#[allow(dead_code)]
#[path = "../../overlay/sk8v/grid.rs"]
mod grid;
#[allow(dead_code)]
#[path = "../../overlay/sk8v/materials.rs"]
mod materials;
#[allow(dead_code)]
#[path = "../../overlay/sk8v/plies.rs"]
mod plies;
#[allow(dead_code)]
#[path = "../../overlay/sk8v/rails.rs"]
mod rails;

mod area;

use bevy_math::Vec3;
use flate2::{Compression, write::ZlibEncoder};
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fs::File;
use std::io::{BufWriter, Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;

/// Tiles to a block's side, and the metres of its neighbours a block is built with.
const BLOCK_TILES: i32 = 2;
const MARGIN: f32 = 16.0;
/// A piece of rail shorter than this, left over where a rail crosses a block's border, is dropped.
const SHORTEST_RAIL: f32 = 0.05;

struct Built {
    triangles: Vec<([Vec3; 3], u32)>,
    rails: Vec<Vec<Vec3>>,
    read: usize,
    toes: usize,
    dropped: usize,
}

#[derive(Default)]
struct Tile {
    triangles: Vec<u8>,
    rails: Vec<u8>,
}

/// The tiles a cache has, and their size.
fn tiles_of(path: &Path) -> Result<(f32, Vec<(i32, i32)>), Box<dyn Error>> {
    let mut file = File::open(path)?;
    let mut head = [0u8; 20];
    file.read_exact(&mut head)?;
    if &head[..4] != b"SVWC" {
        return Err("not a collision.svwc (SK8V's skatev-world-cache writes it)".into());
    }
    let word = |at: usize| u32::from_le_bytes(head[at..at + 4].try_into().unwrap());
    let (size, count) = (f32::from_bits(word(8)), word(12) as usize);
    let mut table = vec![0u8; count * 16];
    file.read_exact(&mut table)?;
    let tiles = table
        .chunks_exact(16)
        .map(|t| (i32::from_le_bytes(t[..4].try_into().unwrap()), i32::from_le_bytes(t[4..8].try_into().unwrap())))
        .collect();
    Ok((size, tiles))
}

/// The pieces of a line of points that lie inside the box lo..hi (XY).
fn clip(rail: &[Vec3], lo: [f32; 2], hi: [f32; 2]) -> Vec<Vec<Vec3>> {
    fn flush(piece: &mut Vec<Vec3>, out: &mut Vec<Vec<Vec3>>) {
        let length: f32 = piece.windows(2).map(|w| (w[1] - w[0]).length()).sum();
        if piece.len() >= 2 && length >= SHORTEST_RAIL {
            out.push(std::mem::take(piece));
        }
        piece.clear();
    }
    let (mut out, mut piece) = (Vec::new(), Vec::new());
    for w in rail.windows(2) {
        let (a, d) = (w[0], w[1] - w[0]);
        let (mut t0, mut t1, mut inside) = (0.0f32, 1.0f32, true);
        for (p, q) in [(-d.x, a.x - lo[0]), (d.x, hi[0] - a.x), (-d.y, a.y - lo[1]), (d.y, hi[1] - a.y)] {
            if p == 0.0 {
                inside &= q >= 0.0;
            } else if p < 0.0 {
                t0 = t0.max(q / p);
            } else {
                t1 = t1.min(q / p);
            }
        }
        if !inside || t0 > t1 {
            flush(&mut piece, &mut out);
            continue;
        }
        if piece.is_empty() || t0 > 0.0 {
            flush(&mut piece, &mut out);
            piece.push(a + d * t0);
        }
        piece.push(a + d * t1);
        if t1 < 1.0 {
            flush(&mut piece, &mut out);
        }
    }
    flush(&mut piece, &mut out);
    out
}

fn build_block(cache: &mut svwc::Cache<std::io::BufReader<File>>, size: f32, block: (i32, i32)) -> Result<Built, Box<dyn Error + Send + Sync>> {
    let side = size * BLOCK_TILES as f32;
    let lo = [block.0 as f32 * side, block.1 as f32 * side];
    let hi = [lo[0] + side, lo[1] + side];
    let centre = [lo[0] + side / 2.0, lo[1] + side / 2.0];
    let reach = side / 2.0 + MARGIN;
    let near = cache.query(centre, reach)?;
    let input: Vec<_> = near
        .iter()
        .filter(|t| {
            let (x, y) = (t.v.map(|p| p[0]), t.v.map(|p| p[1]));
            let (min, max) = (|v: [f32; 3]| v[0].min(v[1]).min(v[2]), |v: [f32; 3]| v[0].max(v[1]).max(v[2]));
            max(x) >= centre[0] - reach && min(x) <= centre[0] + reach && max(y) >= centre[1] - reach && min(y) <= centre[1] + reach
        })
        .map(|t| (t.v, t.material))
        .collect();
    let read = input.len();
    let built = area::build(input.into_iter());
    let within = |p: Vec3| p.x >= lo[0] && p.x < hi[0] && p.y >= lo[1] && p.y < hi[1];
    Ok(Built {
        triangles: built.triangles.into_iter().filter(|(t, _)| within((t[0] + t[1] + t[2]) / 3.0)).collect(),
        rails: built.rails.iter().flat_map(|r| clip(r, lo, hi)).collect(),
        read,
        toes: built.toes,
        dropped: built.dropped,
    })
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (Some(input), Some(output)) = (args.first(), args.get(1)) else {
        return Err("usage: sk8m-bake collision.svwc world.sk8w [threads]".into());
    };
    let threads = args.get(2).and_then(|t| t.parse().ok()).unwrap_or_else(|| std::thread::available_parallelism().map_or(4, |n| n.get())).max(1);
    let began = std::time::Instant::now();
    let (size, tiles) = tiles_of(Path::new(input))?;
    let blocks: Vec<(i32, i32)> = tiles
        .iter()
        .map(|(x, y)| (x.div_euclid(BLOCK_TILES), y.div_euclid(BLOCK_TILES)))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    eprintln!("{} tiles of {size} m, {} blocks, {threads} threads", tiles.len(), blocks.len());

    let tile_of = |v: f32| (v / size).floor() as i32;
    let mut out: BTreeMap<(i32, i32), Tile> = BTreeMap::new();
    let (mut triangles, mut rails, mut points, mut toes, mut dropped, mut read) = (0u64, 0u32, 0u64, 0usize, 0usize, 0usize);
    let next = AtomicUsize::new(0);
    let (send, receive) = mpsc::sync_channel::<Result<Built, String>>(threads * 2);
    std::thread::scope(|scope| {
        for _ in 0..threads {
            let (send, next, blocks) = (send.clone(), &next, &blocks);
            scope.spawn(move || {
                let mut cache = match svwc::Cache::open(Path::new(input)) {
                    Ok(cache) => cache,
                    Err(e) => return drop(send.send(Err(e.to_string()))),
                };
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some(&block) = blocks.get(i) else { break };
                    if send.send(build_block(&mut cache, size, block).map_err(|e| format!("block {block:?}: {e}"))).is_err() {
                        break;
                    }
                }
            });
        }
        drop(send);
        let mut done = 0;
        for built in receive {
            let built = built?;
            for (t, tag) in &built.triangles {
                let (x, y) = (t.map(|p| p.x), t.map(|p| p.y));
                let mut record = [0u8; 40];
                for (i, v) in t.iter().flat_map(|p| p.to_array()).enumerate() {
                    record[i * 4..i * 4 + 4].copy_from_slice(&v.to_le_bytes());
                }
                record[36..].copy_from_slice(&tag.to_le_bytes());
                for tx in tile_of(x[0].min(x[1]).min(x[2]))..=tile_of(x[0].max(x[1]).max(x[2])) {
                    for ty in tile_of(y[0].min(y[1]).min(y[2]))..=tile_of(y[0].max(y[1]).max(y[2])) {
                        out.entry((tx, ty)).or_default().triangles.extend_from_slice(&record);
                    }
                }
                triangles += 1;
            }
            for rail in &built.rails {
                let mut record = Vec::with_capacity(8 + rail.len() * 12);
                record.extend_from_slice(&rails.to_le_bytes());
                record.extend_from_slice(&(rail.len() as u32).to_le_bytes());
                for v in rail.iter().flat_map(|p| p.to_array()) {
                    record.extend_from_slice(&v.to_le_bytes());
                }
                let mut through = BTreeSet::new();
                for w in rail.windows(2) {
                    for tx in tile_of(w[0].x.min(w[1].x))..=tile_of(w[0].x.max(w[1].x)) {
                        for ty in tile_of(w[0].y.min(w[1].y))..=tile_of(w[0].y.max(w[1].y)) {
                            through.insert((tx, ty));
                        }
                    }
                }
                for tile in through {
                    out.entry(tile).or_default().rails.extend_from_slice(&record);
                }
                rails += 1;
                points += rail.len() as u64;
            }
            toes += built.toes;
            dropped += built.dropped;
            read += built.read;
            done += 1;
            if done % 500 == 0 {
                eprintln!("{done} of {} blocks, {:.0} s", blocks.len(), began.elapsed().as_secs_f32());
            }
        }
        Ok::<(), String>(())
    })?;
    eprintln!(
        "{triangles} triangles ({toes} ramp toes added, {dropped} faces left out, {read} read with the margins), {rails} rails with {points} points; packing {} tiles",
        out.len()
    );

    // pack the tiles, several at a time, and write them in order
    let entries: Vec<(&(i32, i32), &Tile)> = out.iter().collect();
    let next = AtomicUsize::new(0);
    let mut packed: Vec<Option<Vec<u8>>> = vec![None; entries.len()];
    let (send, receive) = mpsc::channel::<(usize, std::io::Result<Vec<u8>>)>();
    std::thread::scope(|scope| {
        for _ in 0..threads {
            let (send, next, entries) = (send.clone(), &next, &entries);
            scope.spawn(move || {
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some((_, tile)) = entries.get(i) else { break };
                    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::new(6));
                    let result = encoder.write_all(&tile.triangles).and_then(|_| encoder.write_all(&tile.rails)).and_then(|_| encoder.finish());
                    if send.send((i, result)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(send);
        for (i, result) in receive {
            packed[i] = Some(result?);
        }
        Ok::<(), std::io::Error>(())
    })?;
    let mut file = BufWriter::new(File::create(output)?);
    file.write_all(b"SK8W")?;
    file.write_all(&1u32.to_le_bytes())?;
    file.write_all(&size.to_le_bytes())?;
    file.write_all(&(entries.len() as u32).to_le_bytes())?;
    let mut at = 16 + entries.len() as u64 * 28;
    for (((tx, ty), tile), block) in entries.iter().zip(&packed) {
        let block = block.as_ref().ok_or("a tile was not packed")?;
        file.write_all(&tx.to_le_bytes())?;
        file.write_all(&ty.to_le_bytes())?;
        file.write_all(&at.to_le_bytes())?;
        file.write_all(&(block.len() as u32).to_le_bytes())?;
        file.write_all(&((tile.triangles.len() + tile.rails.len()) as u32).to_le_bytes())?;
        file.write_all(&((tile.triangles.len() / 40) as u32).to_le_bytes())?;
        at += block.len() as u64;
    }
    for block in packed.iter().flatten() {
        file.write_all(block)?;
    }
    file.flush()?;
    eprintln!("{output}: {:.0} MB, {:.0} s", at as f64 / 1e6, began.elapsed().as_secs_f32());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_rail_is_cut_at_the_box_and_keeps_its_height() {
        let rail = [Vec3::new(-2.0, 1.0, 5.0), Vec3::new(2.0, 1.0, 9.0), Vec3::new(6.0, 1.0, 9.0), Vec3::new(6.0, 20.0, 9.0), Vec3::new(1.0, 20.0, 9.0)];
        let pieces = clip(&rail, [0.0, 0.0], [4.0, 4.0]);
        assert_eq!(pieces.len(), 1);
        assert_eq!(pieces[0], vec![Vec3::new(0.0, 1.0, 7.0), Vec3::new(2.0, 1.0, 9.0), Vec3::new(4.0, 1.0, 9.0)]);
        assert_eq!(clip(&rail, [0.0, 0.0], [8.0, 4.0]).len(), 1);
        // (leaves and comes back: two pieces)
        assert_eq!(clip(&rail, [0.0, 0.0], [5.0, 30.0]).len(), 2);
        assert!(clip(&rail, [10.0, 0.0], [12.0, 4.0]).is_empty());
    }
}
