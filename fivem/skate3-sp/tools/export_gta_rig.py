"""GTA V's ped skeleton, from YOUR copy of the game, as the converter reads it (tools/gta_ped_rig.json).

Take `player_one.yft` out of your GTA V with OpenIV or CodeWalker's RPF Explorer
(x64v.rpf \\ models \\ cdimages \\ streamedpeds_players.rpf \\ player_one.yft), then:

usage: python export_gta_rig.py <player_one.yft | player_one.yft.xml> [out.json]

A .yft is turned into CodeWalker XML first (`cwtool` in local_paths.json); a .yft.xml exported with CodeWalker is
read as it is. Per bone the file holds: name, tag (the bone id clips use), parent, head (where the joint is in the
rest pose), world_q (its rest rotation), local_q and local_t (rotation and offset against its parent). Rotations
are (x, y, z, w); the space is the model's own (z up, the ped faces -y, the root turned half round about z).
"""
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import paths
from s3_to_ycd import qmul, qnorm, qrot, vadd

HERE = os.path.dirname(os.path.abspath(__file__))


def to_xml(yft):
    out = os.path.join(tempfile.mkdtemp(), os.path.basename(yft) + ".xml")
    r = subprocess.run([paths.CWTOOL], input=json.dumps({"cmd": "toxml", "in": os.path.abspath(yft), "out": out}),
                       capture_output=True, text=True)
    if not os.path.exists(out):
        sys.exit("cwtool could not read %s: %s" % (yft, (r.stdout or r.stderr)[:400]))
    return out


def read_bones(xml_path):
    bones = ET.parse(xml_path).getroot().find(".//Skeleton/Bones")
    if bones is None:
        sys.exit("%s has no skeleton" % xml_path)
    out = []
    for item in bones.findall("Item"):
        v = lambda tag, keys: tuple(float(item.find(tag).get(k)) for k in keys)
        out.append({"name": item.find("Name").text, "tag": int(item.find("Tag").get("value")),
                    "index": int(item.find("Index").get("value")),
                    "parent_index": int(item.find("ParentIndex").get("value")),
                    "local_t": v("Translation", "xyz"), "local_q": qnorm(v("Rotation", "xyzw"))})
    return sorted(out, key=lambda b: b["index"])


def build(bones):
    """Rest pose by forward kinematics; parents come before their children in the game's skeleton."""
    rig = []
    for b in bones:
        if b["parent_index"] < 0:
            parent, head, world = None, b["local_t"], b["local_q"]
        else:
            p = rig[b["parent_index"]]
            parent = p["name"]
            head = vadd(tuple(p["head"]), qrot(tuple(p["world_q"]), b["local_t"]))
            world = qnorm(qmul(tuple(p["world_q"]), b["local_q"]))
        rig.append({"name": b["name"], "tag": b["tag"], "parent": parent, "head": list(head),
                    "world_q": list(world), "local_q": list(b["local_q"]), "local_t": list(b["local_t"])})
    return rig


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "gta_ped_rig.json")
    rig = build(read_bones(src if src.lower().endswith(".xml") else to_xml(src)))
    json.dump({"source": os.path.basename(src), "bones": rig}, open(out, "w"))
    print("wrote", out, "with", len(rig), "bones")


if __name__ == "__main__":
    main()
