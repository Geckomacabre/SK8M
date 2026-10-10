# cwtool

A small command-line program around [CodeWalker](https://github.com/dexyfex/CodeWalker)'s file library
(`CodeWalker.Core`). The converters use it to turn clip dictionaries and models from CodeWalker XML into the files
GTA V loads, and back. CodeWalker itself is not copied here.

It reads one JSON request on standard input and answers with one JSON object:

```
{"cmd": "tobin", "in": "C:\\work\\ycd_all\\skate3@r.ycd.xml"}
{"cmd": "toxml", "in": "C:\\work\\player_one.yft", "out": "C:\\work\\player_one.yft.xml"}
```

## Build

You need [Git](https://git-scm.com/downloads) and the [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0).
From this folder:

```bat
git init upstream
git -C upstream fetch --depth 1 https://github.com/dexyfex/CodeWalker 485d56bec00262ed7fa472261cce7bbc6202b96e
git -C upstream checkout FETCH_HEAD
dotnet publish CWTool\CWTool.csproj -c Release -o bin
```

That is the CodeWalker revision cwtool was written against. The program is `bin\cwtool.exe`. Put its full path as `cwtool` in `tools/local_paths.json`.

It does not open the game's own encrypted archives. Take files out of GTA V with
[OpenIV](https://openiv.com/) or CodeWalker's RPF Explorer.
