"""Skate 3's own board sounds -> the sound pack of the LOCAL-ONLY resource `skate3_assets`.

Reads the sound archives of YOUR copy of the game (PS3_GAME/USRDIR/data/audio/*.big), decodes the samples the
ride uses (eal3.py), and writes them as .ogg next to a list of what is what (sounds.lua). Nothing here is made
up or synthesised: every file is a recording from the game. It stays on your machine, like the animations.

What is certain and what is a choice
  * rolling: the game names these files by surface (concrete_smooth_hard.grain ...). Each is one long recording
    of a board rolling from slow to fast; the game plays the part that fits the speed, and so does the ride.
  * wheels spinning in the air / in a manual: named by the game (Whls_spins_Jump_1, Whls_spins_Man_1).
  * everything else comes out of banks whose samples have no names (GRINDS, Sk8_Air_Flip_Tricks, Skate_Metal,
    Skate_Collisions, fstep_skateshoe1_sm). The bank says what kind of sound it is; WHICH sample is the pop,
    which the landing and so on was worked out from the shape of the sounds (PICKS below), not read from the
    game. GRINDS holds 41 grinds of three recordings each (slow, medium, fast): all 41 go into the pack so that
    another one can be picked in the game (/skatesound).
  * how loud each sound is against the others, and how speed maps to the rolling recording, are ours: the game
    keeps that in sound patches this tool does not read.

usage: python build_sounds.py [resource_dir]      (default: ~\\skate3-extract\\fivem\\skate3_assets)
"""
import os
import subprocess
import sys

import numpy as np

import eal3
import eb_extract

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO = os.path.normpath(os.path.join(HERE, "..", "..", "PS3_GAME", "USRDIR", "data", "audio"))
import paths  # noqa: E402
DEFAULT_RES = paths.work(r"fivem\skate3_assets")
RATE = 48000      # everything is written at this rate; the player runs at it too, so nothing is resampled twice
PAD = 0.1         # seconds of the loop's own other end either side of it, so the loop points sit in clean sound
QUALITY = "5"     # libvorbis -q:a

# surface -> the game's rolling recording
ROLL = {
    "concrete_smooth": "concrete_smooth_hard.grain",
    "concrete_rough": "concrete_rough_hard.grain",
    "concrete_aggregate": "concrete_aggregate_hard.grain",
    "asphalt_smooth": "asphalt_smooth_hard.grain",
    "asphalt_rough": "asphalt_rough_hard.grain",
    "metal": "metal_smooth_hard.grain",
    "wood": "wood_ramp_hard.grain",
}
ROLL_SPEED = 12.0             # m/s at the end of a rolling recording (ours)
GRIND_SPEEDS = (2.0, 5.0, 8.0)  # m/s at which the slow, medium and fast recording of a grind is the one heard (ours)
GRIND_LEVEL = 4600.0          # every grind's fast recording is brought to this loudness (rms of 16 bit; ours)

# One-off sounds: name -> (archive file, sample numbers, loudness). See the module text: these are picks.
PICKS = {
    "pop":       ("Sk8_Air_Flip_Tricks.abk", [10, 11, 12, 13], 0.9),            # sharp crack, four takes
    "land":      ("Sk8_Air_Flip_Tricks.abk", [14, 15, 16], 0.65),               # short low thump
    "land_big":  ("Sk8_Air_Flip_Tricks.abk", [17, 18, 19, 20, 21, 22, 23], 0.8),  # long thump with the roll-away
    "flip":      ("Sk8_Air_Flip_Tricks.abk", [24, 25, 26], 0.8),                # the board whipping round
    "push":      ("fstep_skateshoe1_sm.abk", list(range(158, 168)), 1.8),       # a skate shoe on the ground
    "lock":      ("Skate_Metal.bnk", [7, 8, 17], 0.5),                          # metal struck
    "bail":      ("Skate_Collisions.bnk", [18, 19, 20, 21, 22, 23], 0.9),       # a body hitting the ground
}
GRINDS = "GRINDS.abk"         # 41 grinds x (slow, medium, fast)
# which of the 41 is heard on what, until another is picked in the game (ours)
GRIND_DEFAULT = {"grind_concrete": 4, "grind_metal": 39, "grind_wood": 29,
                 "slide_concrete": 13, "slide_metal": 14, "slide_wood": 30}


class Archives:
    def __init__(self, folder):
        self.folder, self.open, self.files, self.samples = folder, {}, {}, {}

    def data(self, name):
        if name not in self.files:
            for big in ("audiofiles.big", "grains.big", "wheels.big"):
                if big not in self.open:
                    path = os.path.join(self.folder, big)
                    if not os.path.exists(path):
                        self.open[big] = (None, {})
                        continue
                    f, entries = eb_extract.read_archive(path)
                    self.open[big] = (f, {e[0].replace("\\", "/").rsplit("/", 1)[-1].lower(): e for e in entries})
                f, index = self.open[big]
                e = index.get(name.lower())
                if e:
                    self.files[name] = eb_extract.extract(f, *e[1:])
                    break
            else:
                raise SystemExit("%s is not in the game's sound archives under %s" % (name, self.folder))
        return self.files[name]

    def sample(self, name, k=0):
        if name not in self.samples:
            self.samples[name] = eal3.find(self.data(name))
        found = self.samples[name]
        if k >= len(found):
            raise SystemExit("%s has %d samples, asked for number %d" % (name, len(found), k))
        return found[k]


def encode(path, pcm, rate):
    """int16 mono at `rate` -> .ogg at RATE."""
    r = subprocess.run([eal3.FFMPEG, "-v", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0",
                        "-ar", str(RATE), "-c:a", "libvorbis", "-q:a", QUALITY, path],
                       input=pcm.astype("<i2").tobytes(), capture_output=True)
    if r.returncode != 0:
        raise SystemExit("ffmpeg: " + r.stderr.decode("utf-8", "replace")[:400])


def one_shot(s):
    pcm = s.decode()[:, 0].astype(np.float64)
    n = min(len(pcm), int(s.rate * 0.003))      # 3 ms off the very end, so a sound cut by the game does not click
    if n:
        pcm[-n:] *= np.linspace(1.0, 0.0, n)
    return pcm


def looped(s):
    """A loop with PAD seconds of its own tail before it and of its own head after it."""
    pcm = s.decode()[:, 0].astype(np.float64)
    p = int(round(PAD * s.rate))
    reps = -(-p // len(pcm))
    return np.concatenate([np.tile(pcm, reps)[-p:], pcm, np.tile(pcm, reps)[:p]]), len(pcm) / s.rate


def lua(v, ind=1):
    pad = "  " * ind
    if isinstance(v, dict):
        rows = ["%s  %s = %s," % (pad, k if k.isidentifier() else "['%s']" % k, lua(x, ind + 1)) for k, x in v.items()]
        return "{\n" + "\n".join(rows) + "\n" + pad + "}"
    if isinstance(v, (list, tuple)):
        if v and isinstance(v[0], dict):
            return "{\n" + "\n".join("%s  %s," % (pad, lua(x, ind + 1)) for x in v) + "\n" + pad + "}"
        return "{ " + ", ".join(lua(x, ind) for x in v) + " }"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return "'" + v + "'"
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def write(res):
    """Builds <res>/sounds and <res>/sounds.lua. Returns the table that went into sounds.lua."""
    arc = Archives(AUDIO)
    out = os.path.join(res, "sounds")
    os.makedirs(out, exist_ok=True)
    for old in os.listdir(out):
        if old.endswith(".ogg"):
            os.remove(os.path.join(out, old))
    sounds = {}

    for surface, grain in ROLL.items():
        s = arc.sample(grain)
        pcm = s.decode()[:, 0]
        name = "roll_%s.ogg" % surface
        encode(os.path.join(out, name), pcm, s.rate)
        sounds["roll_" + surface] = {"ramp": True, "files": [name], "seconds": round(len(pcm) / s.rate, 3),
                                     "speed": ROLL_SPEED, "gain": 1.0}

    for name, snr, gain in (("wheels", "Whls_spins_Jump_1.snr", 1.2), ("wheels_manual", "Whls_spins_Man_1.snr", 1.0)):
        s = arc.sample(snr)
        encode(os.path.join(out, name + ".ogg"), s.decode()[:, 0], s.rate)
        sounds[name] = {"once": True, "files": [name + ".ogg"], "gain": gain}

    for name, (bank, numbers, gain) in PICKS.items():
        files = []
        for k in numbers:
            s = arc.sample(bank, k)
            fn = "%s_%d.ogg" % (name, len(files) + 1)
            encode(os.path.join(out, fn), one_shot(s), s.rate)
            files.append(fn)
        sounds[name] = {"files": files, "gain": gain}

    grinds = []
    count = len(eal3.find(arc.data(GRINDS))) // 3
    for g in range(count):
        files, fast = [], 1.0
        for layer in range(3):
            s = arc.sample(GRINDS, g * 3 + layer)
            if not s.loop:
                raise SystemExit("%s sample %d is not a loop" % (GRINDS, g * 3 + layer))
            pcm, seconds = looped(s)
            fn = "grind_%02d_%d.ogg" % (g + 1, layer)
            encode(os.path.join(out, fn), pcm, s.rate)
            files.append({"file": fn, "seconds": round(seconds, 5)})
            fast = float(np.sqrt((pcm * pcm).mean()))
        grinds.append({"layers": True, "files": [f["file"] for f in files], "seconds": [f["seconds"] for f in files],
                       "pad": PAD, "speeds": list(GRIND_SPEEDS), "gain": round(min(2.5, max(0.3, GRIND_LEVEL / fast)), 3)})
    for name, g in GRIND_DEFAULT.items():
        sounds[name] = dict(grinds[g - 1], pick=g)

    pack = {"base": "https://cfx-nui-skate3_assets/sounds/", "rate": RATE, "sounds": sounds,
            "choices": {"grind": grinds}}
    with open(os.path.join(res, "sounds.lua"), "w", newline="\n") as f:
        f.write("-- Skate 3's own board sounds, converted from your own disc by skate3-sp/tools/build_sounds.py.\n"
                "-- LOCAL ONLY, like the animations. sounds = what the ride plays (see html/sound.js in the skateboard\n"
                "-- resource); choices.grind = all the game's grinds, for /skatesound.\n"
                "Skate3Sounds = " + lua(pack, 0) + "\n")
    return pack


def main():
    res = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RES
    pack = write(res)
    folder = os.path.join(res, "sounds")
    files = [f for f in os.listdir(folder) if f.endswith(".ogg")]
    size = sum(os.path.getsize(os.path.join(folder, f)) for f in files)
    print("built %s: %d sounds, %d grinds to pick from, %d files, %.1f MB" % (
        folder, len(pack["sounds"]), len(pack["choices"]["grind"]), len(files), size / 1e6))


if __name__ == "__main__":
    main()
