using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Xml;
using CodeWalker.GameFiles;

namespace CWTool
{
    /// <summary>RPF archive creation, inspection and editing.</summary>
    public static class Rpf
    {
        // ------------------------------------------------------------------ helpers

        public static RpfFile Open(string path)
        {
            path = Path.GetFullPath(path);
            if (!File.Exists(path)) throw new FileNotFoundException("rpf not found: " + path);

            var errors = new List<string>();
            var rpf = new RpfFile(path, Path.GetFileName(path));
            rpf.ScanStructure(null, s => errors.Add(s));

            if (rpf.Root == null)
                throw new InvalidDataException(
                    "could not read RPF structure from " + path +
                    (errors.Count > 0 ? " - " + string.Join("; ", errors) : "") +
                    (rpf.IsAESEncrypted || rpf.IsNGEncrypted
                        ? " (archive is encrypted; only OPEN archives are supported)" : ""));
            return rpf;
        }

        static string[] SplitPath(string p)
        {
            return (p ?? "").Replace('\\', '/').Trim('/').Split(
                new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
        }

        /// <summary>Walk (optionally creating) a directory chain inside an RPF.</summary>
        public static RpfDirectoryEntry EnsureDir(RpfFile rpf, string[] parts, int count, bool create)
        {
            var dir = rpf.Root;
            for (int i = 0; i < count; i++)
            {
                var want = parts[i].ToLowerInvariant();
                RpfDirectoryEntry next = null;
                foreach (var d in dir.Directories)
                {
                    if (d.NameLower == want) { next = d; break; }
                }
                if (next == null)
                {
                    if (!create)
                        throw new DirectoryNotFoundException(
                            "no such directory in archive: " + string.Join("/", parts, 0, i + 1));
                    next = RpfFile.CreateDirectory(dir, parts[i]);
                }
                dir = next;
            }
            return dir;
        }

        public static RpfFileEntry FindFile(RpfFile rpf, string path)
        {
            var parts = SplitPath(path);
            if (parts.Length == 0) throw new ArgumentException("empty entry path");
            var dir = EnsureDir(rpf, parts, parts.Length - 1, false);
            var want = parts[parts.Length - 1].ToLowerInvariant();
            foreach (var f in dir.Files) if (f.NameLower == want) return f;
            throw new FileNotFoundException("no such entry in archive: " + path);
        }

        /// <summary>Read a file from disk, converting *.ytyp.xml / *.ydr.xml / ... to binary
        /// on the way in when <paramref name="autoConvert"/> is set.</summary>
        public static byte[] ReadForImport(string src, bool autoConvert,
                                           out string suggestedName, out string converted)
        {
            converted = null;
            suggestedName = Path.GetFileName(src);
            var namel = suggestedName.ToLowerInvariant();

            bool isGameXml = autoConvert && namel.EndsWith(".xml")
                             && namel.IndexOf('.') != namel.LastIndexOf('.');
            if (!isGameXml) return File.ReadAllBytes(src);

            int trim;
            var format = XmlMeta.GetXMLFormat(namel, out trim);
            var stem = src.Substring(0, src.Length - trim);
            var assetDir = Path.Combine(Path.GetDirectoryName(stem) ?? ".",
                                        Path.GetFileNameWithoutExtension(stem));

            var doc = new XmlDocument();
            doc.LoadXml(File.ReadAllText(src));
            var data = XmlMeta.GetData(doc, format, assetDir);
            if (data == null)
                throw new InvalidOperationException("XML->binary conversion produced nothing for " + src);

            suggestedName = suggestedName.Substring(0, suggestedName.Length - trim);
            converted = XmlMeta.GetXMLFormatName(format);
            return data;
        }

        static RpfEncryption ParseEncryption(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return RpfEncryption.OPEN;
            switch (s.Trim().ToUpperInvariant())
            {
                case "OPEN": case "NONE": return RpfEncryption.OPEN;
                case "AES": return RpfEncryption.AES;
                case "NG": return RpfEncryption.NG;
                default: throw new ArgumentException(
                    "unknown encryption \"" + s + "\" (use OPEN, AES or NG)");
            }
        }

        // ------------------------------------------------------------------ commands

        public static Dictionary<string, object> Create(JsonElement req)
        {
            var path = J.Path(req, "path");
            var overwrite = J.Bool(req, "overwrite");

            if (File.Exists(path))
            {
                if (!overwrite) throw new IOException(
                    "already exists: " + path + " (pass \"overwrite\": true to replace it)");
                File.Delete(path);
            }
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

            var rpf = RpfFile.CreateNew(dir, Path.GetFileName(path),
                                        ParseEncryption(J.Str(req, "encryption")));

            return new Dictionary<string, object>
            {
                { "path", path },
                { "bytes", new FileInfo(path).Length },
                { "encryption", rpf.Encryption.ToString() },
            };
        }

        public static Dictionary<string, object> Add(JsonElement req)
        {
            var rpfPath = J.Path(req, "rpf");
            var rpf = Open(rpfPath);
            var added = AddFiles(rpf, req);
            return new Dictionary<string, object>
            {
                { "rpf", rpfPath },
                { "added", added },
                { "count", added.Count },
                { "bytes", new FileInfo(rpfPath).Length },
            };
        }

        /// <summary>Shared by add / pack / dlc_create.</summary>
        public static List<Dictionary<string, object>> AddFiles(RpfFile rpf, JsonElement req)
        {
            var files = J.Arr(req, "files");
            if (files == null) throw new ArgumentException("\"files\" must be an array");
            var autoConvert = J.Bool(req, "auto_convert", true);
            return AddFiles(rpf, files.Value, autoConvert);
        }

        public static List<Dictionary<string, object>> AddFiles(
            RpfFile rpf, JsonElement files, bool autoConvert)
        {
            var added = new List<Dictionary<string, object>>();
            foreach (var item in files.EnumerateArray())
            {
                string src, dest = null;
                if (item.ValueKind == JsonValueKind.String) src = item.GetString();
                else { src = J.Str(item, "src"); dest = J.Str(item, "dest"); }

                if (string.IsNullOrWhiteSpace(src))
                    throw new ArgumentException("each entry in \"files\" needs a \"src\"");
                src = Path.GetFullPath(src);
                if (!File.Exists(src)) throw new FileNotFoundException("source not found: " + src);

                string suggested, converted;
                var data = ReadForImport(src, autoConvert, out suggested, out converted);

                var destParts = SplitPath(string.IsNullOrWhiteSpace(dest) ? suggested : dest);
                if (destParts.Length == 0) destParts = new[] { suggested };
                var dir = EnsureDir(rpf, destParts, destParts.Length - 1, true);
                var name = destParts[destParts.Length - 1];

                RpfFile.CreateFile(dir, name, data, true);

                var rec = new Dictionary<string, object>
                {
                    { "src", src },
                    { "dest", string.Join("/", destParts) },
                    { "bytes", data.Length },
                };
                if (converted != null) rec["converted_from"] = converted;
                added.Add(rec);
            }
            return added;
        }

        public static Dictionary<string, object> Pack(JsonElement req)
        {
            var path = J.Path(req, "rpf");
            var overwrite = J.Bool(req, "overwrite");

            if (File.Exists(path))
            {
                if (!overwrite) throw new IOException(
                    "already exists: " + path + " (pass \"overwrite\": true to replace it)");
                File.Delete(path);
            }
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

            var rpf = RpfFile.CreateNew(dir, Path.GetFileName(path),
                                        ParseEncryption(J.Str(req, "encryption")));
            var added = AddFiles(rpf, req);

            return new Dictionary<string, object>
            {
                { "rpf", path },
                { "added", added },
                { "count", added.Count },
                { "bytes", new FileInfo(path).Length },
            };
        }

        public static Dictionary<string, object> List(JsonElement req)
        {
            var path = J.Path(req, "rpf");
            var rpf = Open(path);

            var entries = new List<Dictionary<string, object>>();
            Walk(rpf.Root, entries);

            return new Dictionary<string, object>
            {
                { "rpf", path },
                { "bytes", new FileInfo(path).Length },
                { "encryption", rpf.Encryption.ToString() },
                { "version", rpf.Version },
                { "file_count", rpf.TotalFileCount },
                { "folder_count", rpf.TotalFolderCount },
                { "entries", entries },
            };
        }

        static void Walk(RpfDirectoryEntry dir, List<Dictionary<string, object>> outList)
        {
            foreach (var f in dir.Files)
            {
                var res = f as RpfResourceFileEntry;
                outList.Add(new Dictionary<string, object>
                {
                    { "path", f.Path },
                    { "name", f.Name },
                    { "kind", res != null ? "resource" : "binary" },
                    { "size", f.GetFileSize() },
                    { "version", res != null ? (object)res.Version : null },
                });
            }
            foreach (var d in dir.Directories)
            {
                outList.Add(new Dictionary<string, object>
                {
                    { "path", d.Path }, { "name", d.Name }, { "kind", "directory" },
                });
                Walk(d, outList);
            }
        }

        public static Dictionary<string, object> Extract(JsonElement req)
        {
            var path = J.Path(req, "rpf");
            var outDir = Path.GetFullPath(J.Str(req, "out_dir") ??
                                          Path.Combine(Path.GetDirectoryName(path) ?? ".",
                                                       Path.GetFileNameWithoutExtension(path)));
            var rpf = Open(path);

            var targets = new List<RpfFileEntry>();
            var entry = J.Str(req, "entry");
            if (!string.IsNullOrWhiteSpace(entry)) targets.Add(FindFile(rpf, entry));
            else CollectFiles(rpf.Root, targets);

            var rootPath = (rpf.Root.Path ?? "").Replace('\\', '/');
            var written = new List<Dictionary<string, object>>();
            foreach (var f in targets)
            {
                var data = rpf.ExtractFile(f);
                if (data == null)
                    throw new IOException("failed to extract " + f.Path +
                                          (rpf.LastError != null ? ": " + rpf.LastError : ""));

                // Re-attach the RSC7 header so what lands on disk is a real .ydr/.ybn/...
                var res = f as RpfResourceFileEntry;
                if (res != null)
                {
                    data = ResourceBuilder.Compress(data);
                    data = ResourceBuilder.AddResourceHeader(res, data);
                }

                var rel = (f.Path ?? f.Name).Replace('\\', '/');
                if (rootPath.Length > 0 && rel.StartsWith(rootPath, StringComparison.OrdinalIgnoreCase))
                    rel = rel.Substring(rootPath.Length);
                rel = rel.TrimStart('/');
                if (rel.Length == 0) rel = f.Name;

                var dest = Path.GetFullPath(Path.Combine(
                    outDir, rel.Replace('/', Path.DirectorySeparatorChar)));
                Directory.CreateDirectory(Path.GetDirectoryName(dest));
                File.WriteAllBytes(dest, data);
                written.Add(new Dictionary<string, object>
                {
                    { "entry", f.Path }, { "file", dest }, { "bytes", data.Length },
                });
            }

            return new Dictionary<string, object>
            {
                { "rpf", path }, { "out_dir", outDir },
                { "count", written.Count }, { "extracted", written },
            };
        }

        static void CollectFiles(RpfDirectoryEntry dir, List<RpfFileEntry> outList)
        {
            foreach (var f in dir.Files) outList.Add(f);
            foreach (var d in dir.Directories) CollectFiles(d, outList);
        }

        public static Dictionary<string, object> Delete(JsonElement req)
        {
            var path = J.Path(req, "rpf");
            var entryPath = J.Req(req, "entry");
            var rpf = Open(path);
            var entry = FindFile(rpf, entryPath);
            RpfFile.DeleteEntry(entry);
            return new Dictionary<string, object>
            {
                { "rpf", path }, { "deleted", entryPath },
                { "bytes", new FileInfo(path).Length },
            };
        }
    }
}
