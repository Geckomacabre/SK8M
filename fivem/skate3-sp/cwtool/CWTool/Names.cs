using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using CodeWalker.GameFiles;

namespace CWTool
{
    /// <summary>Seeds CodeWalker's global Jenkins hash index so hashes come back as readable
    /// names instead of decimal numbers. Custom names (an MLO archetype, an asset) are stored
    /// in game files as hashes only, so anything not seeded here prints as a number.
    ///
    /// Sources, in order: names named in the request, the stems of every path in the request,
    /// the stems of the files sitting next to those paths, and CodeWalker's own strings.txt.</summary>
    public static class Names
    {
        public static int Indexed;

        public static void Seed(JsonElement req)
        {
            try
            {
                var dirs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                Harvest(req, 0, dirs);

                // Sibling files of anything referenced: an MLO's ytyp usually sits beside
                // vb_int.ydr / vb_int.ybn, which is where the archetype's name comes from.
                foreach (var d in dirs)
                {
                    try
                    {
                        foreach (var f in Directory.GetFiles(d)) EnsureStem(Path.GetFileName(f));
                    }
                    catch (Exception) { }
                }

                for (int i = 0; i < 100; i++) JenkIndex.Ensure(i.ToString("00"));

                // strings.txt ships alongside CodeWalker.Core: a list of known stock names.
                var asmDir = Path.GetDirectoryName(
                    System.Reflection.Assembly.GetExecutingAssembly().Location);
                if (!string.IsNullOrEmpty(asmDir))
                {
                    var fpath = Path.Combine(asmDir, "strings.txt");
                    if (File.Exists(fpath))
                    {
                        foreach (var line in File.ReadAllLines(fpath))
                        {
                            var s = line == null ? null : line.Trim();
                            if (string.IsNullOrEmpty(s) || s.StartsWith("//")) continue;
                            JenkIndex.Ensure(s);
                        }
                    }
                }

                Indexed = JenkIndex.Index.Count;
            }
            catch (Exception)
            {
                // Name resolution is cosmetic - never let it fail a command.
            }
        }

        static void Harvest(JsonElement e, int depth, HashSet<string> dirs)
        {
            if (depth > 8) return;
            switch (e.ValueKind)
            {
                case JsonValueKind.String:
                    var s = e.GetString();
                    EnsureStem(s);
                    RememberDir(s, dirs);
                    break;
                case JsonValueKind.Array:
                    foreach (var i in e.EnumerateArray()) Harvest(i, depth + 1, dirs);
                    break;
                case JsonValueKind.Object:
                    foreach (var p in e.EnumerateObject()) Harvest(p.Value, depth + 1, dirs);
                    break;
            }
        }

        static void RememberDir(string s, HashSet<string> dirs)
        {
            if (string.IsNullOrWhiteSpace(s) || s.Length > 260) return;
            if (s.IndexOf('/') < 0 && s.IndexOf('\\') < 0) return;
            if (dirs.Count > 8) return;
            try
            {
                var d = Path.GetDirectoryName(Path.GetFullPath(s));
                if (!string.IsNullOrEmpty(d) && Directory.Exists(d)) dirs.Add(d);
            }
            catch (Exception) { }
        }

        /// <summary>Register the leaf of a path with every extension stripped:
        /// "foo/bar.ytyp.xml" registers "bar".</summary>
        static void EnsureStem(string s)
        {
            if (string.IsNullOrWhiteSpace(s) || s.Length > 260) return;

            var slash = s.LastIndexOfAny(new[] { '/', '\\' });
            var leaf = slash >= 0 ? s.Substring(slash + 1) : s;
            var dot = leaf.IndexOf('.');
            var stem = dot > 0 ? leaf.Substring(0, dot) : leaf;
            if (stem.Length == 0 || stem.Length > 96) return;

            foreach (var c in stem)
            {
                if (!char.IsLetterOrDigit(c) && c != '_' && c != '-') return;
            }
            JenkIndex.Ensure(stem);
            JenkIndex.Ensure(stem.ToLowerInvariant());
        }
    }
}
