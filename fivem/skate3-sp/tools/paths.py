"""Where things are on this machine.

Everything the tools read comes from YOUR OWN copies of the games, and everything they write goes next to that
data, never into this repository. The defaults fit a work folder `skate3-extract` in your home folder. For other
places copy local_paths.example.json to local_paths.json (it is not tracked) and edit it, or set the environment
variables SK8M_WORK, SK8M_CWTOOL, SK8M_NATIVE_DB.

  work       decoded clips (onboard_csv, offboard_csv, *_meta.csv), vault dumps (vlt, db), miscload, and what the
             tools build there (ycd_all, decks_build, fivem\\skate3_assets)
  cwtool     CodeWalker's command-line converter (clip dictionaries and models, XML <-> the game's binary)
  native_db  a folder with fivem_natives.json and fivem_natives_cfx.json (FiveM's native reference), which the
             tests check every native call against
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL = os.path.join(HERE, "local_paths.json")
_cfg = json.load(open(_LOCAL, encoding="utf-8")) if os.path.exists(_LOCAL) else {}


def _get(key, default):
    value = os.environ.get("SK8M_" + key.upper()) or _cfg.get(key) or default
    return os.path.expandvars(os.path.expanduser(value))


WORK = _get("work", os.path.join("~", "skate3-extract"))
CWTOOL = _get("cwtool", "cwtool.exe")
NATIVE_DB = _get("native_db", "")


def work(*parts):
    """A path inside the work folder."""
    return os.path.join(WORK, *parts)
