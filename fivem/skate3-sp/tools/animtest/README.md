# The animation bank decoder

`decode_anims.py` reads Skate 3's clip banks with **AnimTest**, the Skate-Modding-Team's decoder
(<https://github.com/Skate-Modding-Team/AnimTest>). AnimTest is not copied here. This folder holds what is needed to
build it for the converter:

| File | What it is |
|---|---|
| `animtest.patch` | Three changes to `src/animtest.cpp`: a one-byte fix in the bit reader (without it about half the rotations decode wrong), and two outputs the converter reads (each clip's frame rate, length and root motion; the skeleton block). |
| `shim/` | A small stand-in for the math header AnimTest includes. |
| `build_animtest.bat` | The compile command. |

## Build (Windows)

You need [Git](https://git-scm.com/downloads) and
[Visual Studio 2022](https://visualstudio.microsoft.com/downloads/) with "Desktop development with C++" (the free
Community edition or the Build Tools).

In a folder of your choice, with `animtest.patch`, `shim` and `build_animtest.bat` copied into it:

```bat
git clone https://github.com/Skate-Modding-Team/AnimTest
git -C AnimTest checkout d9a96644e3c0c04ab3ab4b8daefb93329199f739
git -C AnimTest apply --ignore-whitespace ..\animtest.patch

git init EASTL
git -C EASTL fetch --depth 1 https://github.com/electronicarts/EASTL e323f67e5d93fdadcd44f7998069d804697b1945
git -C EASTL checkout FETCH_HEAD

git init EABase
git -C EABase fetch --depth 1 https://github.com/electronicarts/EABase 0699a15efdfd20b6cecf02153bfa5663decb653c
git -C EABase checkout FETCH_HEAD

build_animtest.bat
```

The program is `build\animtest.exe`. Put its full path as `animtest` in `tools/local_paths.json`.

It is built 32-bit on purpose (the bat calls `vcvars32.bat`): AnimTest keeps pointers in 32-bit fields. If Visual
Studio is not in `C:\Program Files\Microsoft Visual Studio\2022\Community`, change the first line of the bat to your
`vcvars32.bat`.
