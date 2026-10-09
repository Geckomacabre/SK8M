"""Static check of every native call in the two resources against the _devtools native database.

The ride tests (ridetest.py) check natives as they are called; this reads the Lua instead, so it also covers the
lines no scenario runs. For every `Name(...)` call in the client / server files:
  - Name must be a FiveM native (Lua spelling of a name in _devtools/_tools/nativedb_src/fivem_natives*.json), a
    function the resource defines itself, or part of the Lua / FiveM runtime;
  - the number of arguments must match the native's parameters (fewer is reported separately: FiveM fills the rest
    with zero, which is only right for a few natives);
  - a client file must not call a server-only native and the other way round.

usage: python devtools_native_check.py [resource_dir ...]   (default: the deployed build's local copies)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
# the devtools kit: DEVTOOLS_PATH, or beside the project folder (wherever that has been moved to), or the Desktop
DEVTOOLS = os.environ.get("DEVTOOLS_PATH") or next(
    (p for p in (os.path.normpath(os.path.join(ROOT, "..", "_devtools")),
                 os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "_devtools"))
     if os.path.isdir(p)), os.path.normpath(os.path.join(ROOT, "..", "_devtools")))
SRC = os.path.join(DEVTOOLS, "_tools", "nativedb_src")
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import paths  # noqa: E402
DEFAULT = [os.path.join(ROOT, "skateboard"), paths.work(r"fivem\skate3_assets")]

# Lua and FiveM runtime functions that are not natives
RUNTIME = set("""assert error ipairs next pairs pcall xpcall select tonumber tostring type rawget rawset rawequal rawlen
setmetatable getmetatable load require print unpack CreateThread Wait SetTimeout RegisterNetEvent AddEventHandler
RemoveEventHandler TriggerEvent TriggerServerEvent TriggerClientEvent TriggerLatentServerEvent RegisterCommand
RegisterKeyMapping RegisterNUICallback SendNUIMessage vector2 vector3 vector4 vec2 vec3 vec4 quat joaat exports
GetHashKey source""".split())
SERVER_FILES = {"server.lua", "deck_server.lua"}


def lua_name(native):
    """SCREAMING_SNAKE (optionally with a leading underscore) -> the Lua global FiveM generates for it."""
    name = native.lstrip("_")
    if name.startswith("0x"):
        return "N_" + name
    # FiveM keeps the underscore in front of a part that starts with a digit (GetGroundZFor_3dCoord)
    return "".join(("_" if p[:1].isdigit() else "") + p[:1].upper() + p[1:].lower() for p in name.split("_"))


def load_db():
    table = {}
    for fn in ("fivem_natives.json", "fivem_natives_cfx.json"):
        data = json.load(open(os.path.join(SRC, fn), encoding="utf-8"))
        for ns, natives in data.items():
            for h, n in natives.items():
                name = n.get("name") or ""
                if not name:
                    continue
                entry = {"name": name, "ns": ns, "params": n.get("params") or [], "apiset": n.get("apiset") or "client",
                         "results": n.get("results") or n.get("return_type") or ""}
                table.setdefault(lua_name(name), []).append(entry)
                for alias in n.get("aliases") or []:
                    table.setdefault(lua_name(alias), []).append(entry)
    return table


def strip(src):
    """Lua source with comments and string contents blanked (same length, so offsets and lines stay)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("--[[", i):
            j = src.find("]]", i)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif src.startswith("--", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(c + "s" * max(0, j - i - 1) + c)
            i = j + 1
        elif src.startswith("[[", i):
            j = src.find("]]", i)
            j = n if j < 0 else j + 2
            out.append("'" + re.sub(r"[^\n]", "s", src[i + 1:j - 1]) + "'")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


OPEN, CLOSE = {"function", "do", "if", "repeat"}, {"end", "until"}


def count_args(code, start):
    """code[start] is the '(' of a call: the number of top-level arguments (commas inside brackets or inside a
    function body passed as an argument do not count)."""
    depth, block, i, args, seen = 0, 0, start, 0, False
    while i < len(code):
        c = code[i]
        if c.isalpha() or c == "_":
            j = i
            while j < len(code) and (code[j].isalnum() or code[j] == "_"):
                j += 1
            word = code[i:j]
            block += 1 if word in OPEN else (-1 if word in CLOSE else 0)
            seen, i = True, j
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return args + (1 if seen else 0)
        elif c == "," and depth == 1 and block == 0:
            args += 1
        elif depth >= 1 and not c.isspace():
            seen = True
        i += 1
    return None


def lua_params(params):
    """The parameters a Lua call passes: pointer parameters are results in Lua (a char* is a string argument)."""
    return [p for p in params if not str(p.get("type", "")).endswith("*") or str(p.get("type", "")).startswith(("char", "const char"))]


def main():
    db = load_db()
    dirs = sys.argv[1:] or DEFAULT
    files = []
    for d in dirs:
        files += [f for f in sorted(glob.glob(os.path.join(d, "*.lua"))) if os.path.basename(f) != "fxmanifest.lua"]
    stripped = {f: strip(open(f, encoding="utf-8").read()) for f in files}
    defined = set()
    for code in stripped.values():
        defined |= set(re.findall(r"\bfunction\s+([A-Za-z_][\w.:]*)", code))
        defined |= set(re.findall(r"\blocal\s+function\s+([A-Za-z_]\w*)", code))
        defined |= set(re.findall(r"\b([A-Za-z_]\w*)\s*=\s*function\b", code))
        defined |= set(m for grp in re.findall(r"\blocal\s+([A-Za-z_][\w\s,]*?)\s*(?:=|\n)", code) for m in re.split(r"[\s,]+", grp) if m)
    defined |= {d.split(".")[-1].split(":")[-1] for d in defined}

    calls = bad = short = 0
    used, unknown, wrong_side, mismatch, fewer = {}, {}, [], [], []
    for f, code in stripped.items():
        base = os.path.basename(f)
        side = "server" if base in SERVER_FILES else "client"
        for m in re.finditer(r"(?<![\w.:])([A-Z][A-Za-z0-9_]*)\s*\(", code):
            name = m.group(1)
            line = code.count("\n", 0, m.start()) + 1
            before = code[max(0, m.start() - 12):m.start()]
            if re.search(r"function\s+$", before):
                continue  # a definition, not a call
            if name in db:
                calls += 1
                used[name] = used.get(name, 0) + 1
                n = count_args(code, m.end() - 1)
                entries = db[name]
                # an entity pointer (DeleteObject(Object*)) is passed in Lua, other pointers are results: anything
                # from "no pointers" to "all parameters" is a possible Lua call
                want = sorted({k for e in entries for k in range(len(lua_params(e["params"])), len(e["params"]) + 1)})
                api = {e["apiset"] for e in entries}
                if side == "client" and api == {"server"} or side == "server" and api == {"client"}:
                    wrong_side.append(f"{base}:{line} {name} is a {'/'.join(api)} native, called on the {side}")
                if n not in want:
                    params = ", ".join(f"{p.get('type', '?')} {p.get('name', '?')}" for p in lua_params(entries[0]["params"]))
                    (fewer if n is not None and n < min(want) else mismatch).append(
                        f"{base}:{line} {name} called with {n}, takes {want[0]} ({params})")
            elif name not in defined and name not in RUNTIME:
                unknown.setdefault(name, []).append(f"{base}:{line}")

    print(f"{len(files)} Lua files, {calls} native calls, {len(used)} different natives (database: {SRC})")
    for title, rows in (("wrong argument count", mismatch), ("fewer arguments than parameters (FiveM passes zero for the rest)", fewer),
                        ("wrong side", wrong_side)):
        print(f"{'OK  ' if not rows else ('NOTE' if rows is fewer else 'BAD ')}{title}: {len(rows)}")
        for r in rows:
            print("      " + r)
    print(f"{'BAD ' if unknown else 'OK  '}calls to names that are neither natives nor defined in the resource: {len(unknown)}")
    for name, where in sorted(unknown.items()):
        print(f"      {name}: {', '.join(where[:6])}")
    ok = not mismatch and not wrong_side and not unknown
    print("ALL OK" if ok else "CHECK THE LINES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
