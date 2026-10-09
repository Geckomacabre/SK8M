"""Skate 3's own tuning numbers -> skate3_assets/tuning.lua (LOCAL ONLY, like the rest of skate3_assets).

The numbers come from YOUR copy of the game: data/db/skatercollections.vlt/.bin + skaterschema.vlt/.bin (EA "AttribSys"
vaults), decoded by tools/vlt/vlt_parse.py into JSON (one file per class, attribute names proven by their 64-bit
hashes). This script picks the attributes the skateboard controller understands and writes them as a Lua table the
controller reads through skate3_assets' Tuning export. Only attributes with a proven NAME are used; what each one
does in the controller is documented in skateboard/tuning.lua.

usage: python build_tuning.py [out.lua]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
DB = paths.work(r"db\data\db")
DUMP = paths.work(r"vlt\dump")
PARSER = os.path.join(HERE, "vlt", "vlt_parse.py")

MODES = ("easy", "normal", "hardcore")
SURFACES = ("smooth", "rough", "slippery", "slow", "veryslow")  # physics_surfaces collections
# camera shots the controller uses (camera_shots collections)
SHOTS = ("chase_flat_slow", "chase_flat_fast", "chase_up_slow", "chase_down_slow", "air_small", "air_big", "air_landing",
         "grind_flat_slow", "grind_flat_fast", "close_manual", "far_manual", "high_chase", "skitching")
SHOT_KEYS = {"PositionDistance": "distance", "PositionHeading": "heading", "PositionElevation": "elevation",
             "ReferenceBoardOffset": "boardOffset", "ReferenceWeightBoard": "weightBoard", "ReferenceWeightCOM": "weightCOM",
             "FramingYaw": "yaw", "FramingPitch": "pitch", "FramingRoll": "roll", "FramingLensLength": "lens",
             "SmoothingYaw": "smoothYaw", "SmoothingPitch": "smoothPitch", "SmoothingElevation": "smoothElevation",
             "SmoothingDirection": "smoothDirection", "TransitionTime": "transition"}


def ensure_dump():
    if os.path.isdir(DUMP) and os.path.exists(os.path.join(DUMP, "physics_push.json")):
        return
    r = subprocess.run([sys.executable, PARSER, "--db", DB, "--dump", DUMP], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("vlt_parse failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])


class Vault:
    def __init__(self):
        self.cache = {}

    def cls(self, name):
        if name not in self.cache:
            self.cache[name] = json.load(open(os.path.join(DUMP, name + ".json"), encoding="utf-8"))
        return self.cache[name]

    def get(self, cls, collection, attr):
        """The value of a NAMED attribute. Missing = the dump no longer matches this script: stop."""
        cols = self.cls(cls)["collections"]
        if collection not in cols:
            sys.exit(f"{cls}: no collection '{collection}'")
        vals = cols[collection]["values"]
        if attr not in vals:
            sys.exit(f"{cls}/{collection}: attribute '{attr}' is not in the dump (name not recovered?)")
        return vals[attr]["value"]

    def graph(self, cls, collection, attr):
        g = self.get(cls, collection, attr)
        if not isinstance(g, dict) or "x" not in g or len(g["x"]) != len(g["y"]):
            sys.exit(f"{cls}/{collection}.{attr} is not a graph")
        return {"x": list(g["x"]), "y": list(g["y"])}

    def collections(self, cls):
        return self.cls(cls)["collections"]


def lua(v, ind=1):
    """Python value -> Lua literal."""
    pad = "  " * ind
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:.7g}"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(lua(x, ind + 1) for x in v) + " }"
    if isinstance(v, dict):
        if set(v) == {"x", "y"}:  # a graph: one line
            return "{ x = " + lua(v["x"]) + ", y = " + lua(v["y"]) + " }"
        rows = []
        for k, x in v.items():
            key = k if k.isidentifier() else f"[{json.dumps(k)}]"
            rows.append(f"{pad}{key} = {lua(x, ind + 1)},")
        return "{\n" + "\n".join(rows) + "\n" + "  " * (ind - 1) + "}"
    raise TypeError(type(v))


def build():
    ensure_dump()
    v = Vault()
    t = {}
    t["gravity"] = -v.get("physics", "default", "WorldGravity")[1]
    t["push"] = {"maxSpeed": v.get("physics_push", "default", "MaxPushableSpeed")}
    t["jump"] = {
        "absoluteMinHeight": v.get("physics_jump", "default", "AbsoluteMinHeight"),
        "speedResponseMaxSpeed": v.get("physics_jump", "default", "SpeedResponseMaxSpeed"),
        "minHeightVsSpeed": v.graph("physics_jump", "default", "MinHeightVsSpeed"),
        "maxHeightVsSpeed": v.graph("physics_jump", "default", "MaxHeightVsSpeed"),
    }
    t["modes"] = {}
    for m in MODES:
        t["modes"][m] = {
            "jumpMinHeight": v.get("physics_mode", m, "JumpMinHeight"),
            "jumpMaxHeight": v.get("physics_mode", m, "JumpMaxHeight"),
            "pushDVStart": v.get("physics_mode", m, "MaxPushDVStart"),
            "pushDVEnd": v.get("physics_mode", m, "MaxPushDVEnd"),
            "grindLockDist": v.get("physics_mode", m, "GrindLockDist"),
            "maxAutoBodySpinSpeed": v.get("physics_mode", m, "MaxAutoBodySpinSpeed"),
            "autoPush": v.get("physics_mode", m, "AutoPushEnabled"),
            "easyBodySpins": v.get("physics_mode", m, "EasyBodySpins"),
        }
    t["friction"] = {
        "surface": v.graph("physics_surfaces", "smooth", "FrictionVsSpeedNew"),
        # ... and for the other kinds of ground the game knows, with how much harder the brake bites on each
        "surfaces": {c: v.graph("physics_surfaces", c, "FrictionVsSpeedNew") for c in SURFACES},
        "braking": {c: v.get("physics_surfaces", c, "BrakingScalar") for c in SURFACES},
        "noInput": v.graph("physics_friction", "default", "FrictionVsSpeed_NoInput"),
        "noInputTime": v.get("physics_friction", "default", "NoInputTime"),
        "manual": v.graph("physics_friction", "default", "FrictionVsSpeed_Manual"),
    }
    # a foot plant off the ground (boneless, fastplant, no comply): how fast the jump leaves the ground by how steep
    # it is there (1 = flat), and what is left of the rolling speed by that speed
    t["boneless"] = {"jumpSpeedVsNormal": v.graph("physics_state_boneless", "default", "JumpNormalSpeedVsNormalY"),
                     "planarVsSpeed": v.graph("physics_state_boneless", "default", "JumpPlanarVsPlanarSpeed")}
    # the hippy jump: how high the rider's hips go (like the jump heights: from the same floor, AbsoluteMinHeight)
    t["hippy"] = {"minHeight": v.get("physics_jump", "default", "HippyJumpMinHeight"),
                  "maxHeight": v.get("physics_jump", "default", "HippyJumpMaxHeight"),
                  "floor": v.get("physics_jump", "default", "AbsoluteMinHeight")}
    # a revert: how fast the board turns (radians per second) by how far round it is (radians)
    t["revert"] = {"rotSpeedVsAngle": v.graph("physics_revert", "default", "RotSpeedVsAngle")}
    # the most a slope may speed the board up or slow it down, m/s per second
    t["slope"] = {"maxGravityAcceleration": v.get("physics_speed_conservation", "default", "MaxGravityAcceleration"),
                  # the board's acceleration while the rider lies on it (the coffin), m/s per second
                  "coffinAcceleration": v.get("physics_speed_conservation", "default", "CoffinAcceleration")}
    # holding on to the back of a car. The box the game looks in for something to hold sits GrabbableBoxOffset
    # ahead of the skater and is GrabbableBoxSizeInto to each side of that (read as half sizes: across, along, up)
    sk = lambda a: v.get("physics_state_skitching", "default", a)
    t["skitch"] = {
        "reach": sk("GrabbableBoxOffset")[1] + sk("GrabbableBoxSizeInto")[1],
        "side": sk("GrabbableBoxSizeInto")[0],
        "minTime": sk("EnterSkitchMinTime"),
        "again": sk("DelayUntilReskitchable"),
        "exitFwd": sk("ExitPushForwardSpeedDelta"),
        "exitBack": sk("ExitPushBackSpeedDelta"),
        "exitDist": sk("ExitDist"),
        "drop": sk("NaturalAirMaxDist"),
        "edge": sk("DistanceToHoldOffFromGrabSplineEdge"),
        "hand": sk("LeftHandOffset"),
        "shimmy": v.get("anim_skitching", "default", "ShimmySpeedMax"),
        # the fastest closing speed the game has a hold animation for (where its "absorb" graph ends)
        "maxClose": v.graph("anim_skitching", "default", "AbsorbContactSpeedMapping")["x"][-1],
    }
    # off the board (walking, running with the board in the hand): how fast the skater may turn, by speed
    t["offboard"] = {"turnVsSpeed": v.graph("physics_biped", "default", "TurnVsSpeed")}
    # a drop the wheels stay on, and how short a fall is no jump at all
    t["air"] = {
        "naturalAirMaxDist": v.get("physics_airstates", "default", "NaturalAirMaxDist"),
        "naturalAirTime": v.get("physics_airstates", "default", "NaturalAirTime"),
    }
    # banks and ramps
    t["transition"] = {
        # how much of gravity's pull across the board turns it down the hill, by the slope (read as its sine)
        "carveVsSlope": v.graph("physics_heading", "default", "HeadingAdjustVsSlope"),
        # how much more of a pop there is off a steep face, by how upright the face's normal is (1 = level ground)
        "jumpVsNormal": v.graph("physics_jump", "default", "JumpYScalarVsGroundNormalY"),
        # what a landing on a face that steep makes of the board's speed
        "landingVsNormal": v.graph("physics_airstates", "default", "LandingSpeedScalarVsGroundNormalY"),
        # in the air: how much of the way the rider comes round to the ground under the landing, each tick
        "alignToGround": v.get("physics_airstates", "default", "SpeedToAlignToGround_PhysAir"),
    }
    t["steering"] = {
        "damping": v.get("physics_steering", "default", "Damping"),
        "vsInput": v.graph("physics_steering", "default", "SteeringVsInput"),
        "vsSpeed": v.graph("physics_steering", "default", "SteeringVsSpeed"),
        "vsSpeedMaxSpeed": v.get("physics_steering", "default", "SteeringVsSpeedMaxSpeed"),
    }
    t["bodyspin"] = {
        "vsTime": v.graph("physics_bodyspin", "default", "PropBodySpinVsTime"),
        "maxSpinSpeed": v.get("physics_airstates", "default", "MaxSpinSpeed"),
    }
    t["grind"] = {
        "deckCenterToTruck": v.get("physics_grinds", "default", "DeckCenterToTruck"),
        "frictionCoefficient": v.get("physics_grinds", "default", "FrictionCoefficient"),
        "frictionVsTime": v.graph("physics_grinds", "default", "FrictionVsTime"),
        "angleRange5050": v.get("physics_grinds_air", "default", "AngleRange50_50"),
        "angleRangeBoardSlide": v.get("physics_grinds_air", "default", "AngleRangeBoardSlide"),
        "angleRangeTipSlide": v.get("physics_grinds_air", "default", "AngleRangeTipSlide"),
        "maxOffsetDeltaPerFrame": v.get("physics_grinds_air", "default", "MaxOffsetDeltaPerFrame"),
    }
    t["wipeout"] = {
        "airMaxSpeedIntoGround": v.get("physics_wipeout", "default", "Wipeout_AirMaxSpeedIntoGround"),
        "groundMaxAngularDeckError": v.get("physics_wipeout", "default", "Wipeout_GroundMaxAngularDeckError"),
    }
    shots = {}
    for name in SHOTS:
        vals = v.collections("camera_shots")[name]["values"]
        shots[name] = {new: vals[old]["value"] for old, new in SHOT_KEYS.items()
                       if old in vals and isinstance(vals[old]["value"], (int, float)) and not isinstance(vals[old]["value"], bool)}
    t["camera"] = {"shots": shots}

    base = {}
    for name, c in v.collections("scoring_trick").items():
        score = c["values"].get("BaseScore", {}).get("value")
        if isinstance(score, (int, float)) and not name.endswith("_class"):
            base[name] = score
    g = lambda a: v.get("scoring2_general", "default", a)
    s = lambda a: v.get("scoring2_states", "default", a)
    t["scoring"] = {
        "base": dict(sorted(base.items())),
        "airGrabTime": v.graph("scoring2_states", "default", "AirGrabTimeScore"),
        "airPlayerSpin": v.graph("scoring2_states", "default", "AirPlayerSpin"),
        "grindLength": v.graph("scoring2_states", "default", "GrindLengthScore"),
        "manualDist": v.graph("scoring2_states", "default", "ManualDistScore"),
        "duplicatePenalty": v.graph("scoring2_general", "default", "DuplicateTrickPenalty"),
        "momentum": [[g("MomentumMeterFirstMultiplierPointThreshold"), g("MomentumMeterFirstMultiplier")],
                     [g("MomentumMeterSecondMultiplierPointThreshold"), g("MomentumMeterSecondMultiplier")],
                     [g("MomentumMeterThirdMultiplierPointThreshold"), g("MomentumMeterThirdMultiplier")]],
        "momentumMaxPoints": g("MomentumMeterMaxPoints"),
        "momentumPointsPerSecond": g("MomentumMeterPointsPerSecond"),
        "manualMinSpeed": g("ManualMinSpeed"),
        "lineSeconds": s("MaxSecondsGroundSequenceMaintainsLine"),
        "fromFakie": s("AirFromFakieBonusScale"),
        "fromManual": s("AirFromManualBonusScale"),
        "fromGrind": s("AirFromGrindBonusScale"),
        "fromStationary": s("AirFromStationaryBonusScale"),
        "stationarySpeed": s("AirLaunchMinGroundSpeedForNonStationary"),
        "toGrind": s("AirToGrindBonusScale"),
        "toSketchy": s("AirToSketchyLandingPointScale"),
        "spinThreshold": s("AirThresholdFor180Spins"),
    }
    return t


def write(path):
    t = build()
    text = ("-- Skate 3's own tuning, decoded from YOUR copy of the game (data/db/skatercollections) by skate3-sp/tools.\n"
            "-- LOCAL ONLY, like everything in skate3_assets. Units as the game stores them (metres, m/s, degrees where the\n"
            "-- name says so); graphs are { x = {...}, y = {...} } points to interpolate between.\n"
            "Skate3Tuning = " + lua(t) + "\n")
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    return t


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(paths.work(r"fivem\skate3_assets"), "tuning.lua")
    t = write(out)
    print("wrote", out, "-", len(t["scoring"]["base"]), "trick scores,", len(t["camera"]["shots"]), "camera shots, modes",
          ", ".join(t["modes"]))
