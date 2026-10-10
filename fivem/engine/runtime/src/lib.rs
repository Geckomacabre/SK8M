//! Skate 3's engine behind a C interface a WebAssembly host can call.
//!
//! The host owns the loop. It loads a rider with the game's data folder and the ground under them, then each
//! engine tick (60 a second) hands over that rider's pad as an Xbox pad reports it and reads back where the board
//! and every bone are. One instance carries any number of riders, each under a number the host picks; the game's
//! data is read once and shared. All numbers are in Skate 3's own space: metres, y up.
//!
//! Memory: the host asks for a block with `sk8m_alloc`, writes into it, and gives it back with `sk8m_free`.
//! Every function that can fail returns 0 for success; `sk8m_error` then has nothing, otherwise the reason.
use skate_host::bridge::{Controls, Session};
use std::cell::RefCell;
use std::collections::HashMap;
use std::path::Path;

struct Rider {
    session: Session,
    state: String,
}

#[derive(Default)]
struct Engine {
    riders: HashMap<u32, Rider>,
    error: String,
}

thread_local! {
    static ENGINE: RefCell<Engine> = RefCell::new(Engine::default());
}

fn fail(e: &mut Engine, reason: String) -> i32 {
    e.error = reason;
    1
}

fn done(e: &mut Engine, result: Option<Result<(), String>>) -> i32 {
    match result {
        Some(Ok(())) => 0,
        Some(Err(reason)) => fail(e, reason),
        None => fail(e, "no such rider".into()),
    }
}

unsafe fn text<'a>(ptr: *const u8, len: usize) -> &'a str {
    std::str::from_utf8(unsafe { std::slice::from_raw_parts(ptr, len) }).unwrap_or("")
}

/// `count` triangles as 9 floats each (three corners, x y z).
unsafe fn triangles(ptr: *const f32, count: usize) -> Vec<[[f32; 3]; 3]> {
    let flat = if count == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(ptr, count * 9) } };
    flat.chunks_exact(9)
        .map(|t| [[t[0], t[1], t[2]], [t[3], t[4], t[5]], [t[6], t[7], t[8]]])
        .collect()
}

/// Rails as floats: for each rail its number of points, then the points (x y z each).
unsafe fn rails(ptr: *const f32, len: usize) -> Vec<Vec<[f32; 3]>> {
    let flat = if len == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(ptr, len) } };
    let mut out = Vec::new();
    let mut at = 0;
    while at < flat.len() {
        let n = flat[at] as usize;
        at += 1;
        if at + n * 3 > flat.len() {
            break;
        }
        out.push(flat[at..at + n * 3].chunks_exact(3).map(|p| [p[0], p[1], p[2]]).collect());
        at += n * 3;
    }
    out
}

fn copy_out(text: &str, out: *mut u8, cap: usize) -> usize {
    let n = text.len().min(cap);
    unsafe { std::ptr::copy_nonoverlapping(text.as_ptr(), out, n) };
    n
}

#[unsafe(no_mangle)]
pub extern "C" fn sk8m_alloc(bytes: usize) -> *mut u8 {
    let mut block = Vec::<u64>::with_capacity(bytes.div_ceil(8).max(1));
    let ptr = block.as_mut_ptr();
    std::mem::forget(block);
    ptr.cast()
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_free(ptr: *mut u8, bytes: usize) {
    drop(unsafe { Vec::<u64>::from_raw_parts(ptr.cast(), 0, bytes.div_ceil(8).max(1)) });
}

/// A rider: loads the game's data from the folder `root` and builds their world from the triangles and rails
/// given, the rider standing at x, y, z facing `heading` (radians about y). A rider already under `id` is replaced.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_load(
    id: u32,
    root: *const u8, root_len: usize,
    tris: *const f32, tri_count: usize,
    rail_floats: *const f32, rail_len: usize,
    x: f32, y: f32, z: f32, heading: f32,
) -> i32 {
    let root = unsafe { text(root, root_len) }.to_owned();
    let (tris, rails) = unsafe { (triangles(tris, tri_count), rails(rail_floats, rail_len)) };
    ENGINE.with_borrow_mut(|e| {
        e.riders.remove(&id);
        let loaded = Session::new(Path::new(&root), tris, rails, [x, y, z], heading)
            .and_then(|mut session| session.activate([x, y, z], heading).map(|_| session));
        match loaded {
            Ok(session) => {
                e.riders.insert(id, Rider { session, state: String::new() });
                e.error.clear();
                0
            }
            Err(reason) => fail(e, reason),
        }
    })
}

/// The rider is done with.
#[unsafe(no_mangle)]
pub extern "C" fn sk8m_close(id: u32) {
    ENGINE.with_borrow_mut(|e| {
        e.riders.remove(&id);
    });
}

/// Seconds one tick stands for (0 for a rider there is not).
#[unsafe(no_mangle)]
pub extern "C" fn sk8m_period(id: u32) -> f32 {
    ENGINE.with_borrow(|e| e.riders.get(&id).map_or(0.0, |r| r.session.period()))
}

/// Puts the rider at a place (the engine's own teleport), facing `heading` (radians about y).
#[unsafe(no_mangle)]
pub extern "C" fn sk8m_place(id: u32, x: f32, y: f32, z: f32, heading: f32) -> i32 {
    ENGINE.with_borrow_mut(|e| {
        let result = e.riders.get_mut(&id).map(|r| r.session.activate([x, y, z], heading).map(|_| ()));
        done(e, result)
    })
}

/// Replaces the world the rider is in.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_world(id: u32, tris: *const f32, tri_count: usize, rail_floats: *const f32, rail_len: usize) -> i32 {
    let (tris, rails) = unsafe { (triangles(tris, tri_count), rails(rail_floats, rail_len)) };
    ENGINE.with_borrow_mut(|e| {
        let result = e.riders.get_mut(&id).map(|r| {
            r.session.collision_builder().build(tris, rails).and_then(|world| r.session.install_collision(world))
        });
        done(e, result)
    })
}

/// One engine tick with the pad as XInput reports it: button bits, triggers 0..255, sticks -32768..32767.
#[unsafe(no_mangle)]
pub extern "C" fn sk8m_tick(id: u32, buttons: u32, left_trigger: u32, right_trigger: u32, lx: i32, ly: i32, rx: i32, ry: i32) -> i32 {
    let stick = |v: i32| v.clamp(i16::MIN as i32, i16::MAX as i32) as i16;
    let controls = Controls {
        buttons: buttons as u16,
        triggers: [left_trigger.min(255) as u8, right_trigger.min(255) as u8],
        left: [stick(lx), stick(ly)],
        right: [stick(rx), stick(ry)],
    };
    ENGINE.with_borrow_mut(|e| {
        let result = e.riders.get_mut(&id).map(|r| r.session.tick(controls));
        done(e, result)
    })
}

/// Writes the pose as floats and returns the number of bones (0 for a rider there is not): the root's matrix (16,
/// column by column: the board's place in the world), the board's velocity (3), the camera (position 3, basis 9,
/// field of view 1; all 0 with no camera), then one matrix (16) per bone against the root, as many as fit in `cap`
/// floats.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_pose(id: u32, out: *mut f32, cap: usize) -> u32 {
    ENGINE.with_borrow_mut(|e| {
        let Some(rider) = e.riders.get_mut(&id) else { return 0 };
        let pose = rider.session.pose();
        let out = unsafe { std::slice::from_raw_parts_mut(out, cap) };
        let mut at = 0;
        let mut put = |values: &[f32]| {
            if at + values.len() <= out.len() {
                out[at..at + values.len()].copy_from_slice(values);
            }
            at += values.len();
        };
        put(&pose.root.to_cols_array());
        put(&pose.velocity.to_array());
        match pose.camera {
            Some((position, basis, fov)) => {
                put(&position.to_array());
                put(&basis.to_cols_array());
                put(&[fov]);
            }
            None => put(&[0.0; 13]),
        }
        for bone in &pose.bones {
            put(&bone.to_cols_array());
        }
        rider.state = pose.state;
        pose.bones.len() as u32
    })
}

/// The bones' names, one per line, in the order `sk8m_pose` writes them. Returns the bytes written.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_bone_names(id: u32, out: *mut u8, cap: usize) -> usize {
    ENGINE.with_borrow(|e| e.riders.get(&id).map_or(0, |r| copy_out(&r.session.pose().names.join("\n"), out, cap)))
}

/// What the rider is doing, as the engine names it (as of their last `sk8m_pose`).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_state(id: u32, out: *mut u8, cap: usize) -> usize {
    ENGINE.with_borrow(|e| e.riders.get(&id).map_or(0, |r| copy_out(&r.state, out, cap)))
}

/// Why the last call failed.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn sk8m_error(out: *mut u8, cap: usize) -> usize {
    ENGINE.with_borrow(|e| copy_out(&e.error, out, cap))
}
