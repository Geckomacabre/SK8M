//! Does the real Skate 3 engine ride on this PC, on this disc's data?
//!
//! A flat floor, the rider put on it, then a scripted pad: nothing, three pushes (A), roll, a turn on the left
//! stick, an ollie on the right stick. Prints where the board is, how fast, and what the engine says the rider does.
//!
//! usage: sk8m-probe <assets root>      (the folder with private/game.json)
use skate_host::bridge::{Controls, Session};
use std::path::Path;

const A: u16 = 0x1000;

fn main() {
    let root = std::env::args().nth(1).expect("usage: sk8m-probe <assets root>");
    if let Err(e) = run(Path::new(&root)) {
        eprintln!("FAILED: {e}");
        std::process::exit(1);
    }
}

fn run(root: &Path) -> Result<(), String> {
    // Skate space: y up. Two triangles, normal up.
    let s = 300.0f32;
    let floor = vec![
        [[-s, 0.0, -s], [-s, 0.0, s], [s, 0.0, -s]],
        [[s, 0.0, -s], [-s, 0.0, s], [s, 0.0, s]],
    ];
    let mut session = Session::new(root, floor, vec![], [0.0, 0.0, 0.0], 0.0)?;
    let period = session.period();
    println!("loaded; one tick = {:.5} s ({:.1} Hz)", period, 1.0 / period);
    let pose = session.activate([0.0, 0.0, 0.0], 0.0)?;
    println!("on the board: {} bones, state {}", pose.bones.len(), pose.state);

    let hz = (1.0 / period).round() as u64;
    let mut controls = Controls::default();
    let mut top_speed = 0.0f32;
    let mut top_height = f32::MIN;
    for tick in 0..(hz * 16) {
        let t = tick as f32 * period;
        controls = Controls::default();
        // three pushes, each a quarter of a second of A
        for push in [1.0f32, 2.0, 3.0] {
            if t >= push && t < push + 0.25 {
                controls.buttons = A;
            }
        }
        // a turn: left stick to the right for a second and a half
        if (7.0..8.5).contains(&t) {
            controls.left = [20000, 0];
        }
        // an ollie: right stick down, then flicked up
        if (11.0..11.4).contains(&t) {
            controls.right = [0, -32767];
        } else if (11.4..11.5).contains(&t) {
            controls.right = [0, 32767];
        }
        session.tick(controls)?;
        let pose = session.pose();
        let p = pose.root.w_axis;
        let speed = pose.velocity.length();
        top_speed = top_speed.max(speed);
        top_height = top_height.max(p.y);
        if tick % (hz / 2) == 0 {
            println!(
                "t {:5.2}  pos {:8.3} {:7.3} {:8.3}  speed {:6.3}  vel {:6.2} {:6.2} {:6.2}  {}",
                t, p.x, p.y, p.z, speed, pose.velocity.x, pose.velocity.y, pose.velocity.z, pose.state
            );
        }
    }
    println!("top speed {top_speed:.3} m/s, highest root {top_height:.3} m");
    Ok(())
}
