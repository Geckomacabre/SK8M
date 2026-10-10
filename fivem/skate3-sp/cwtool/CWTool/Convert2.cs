using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Xml;
using CodeWalker.GameFiles;

namespace CWTool
{
    /// <summary>Binary game file &lt;-&gt; CodeWalker XML, mirroring what RPF Explorer's
    /// "Export XML" / "Import XML" do, including the sibling texture folder convention.</summary>
    public static class Convert2
    {
        /// <summary>Build the RpfFileEntry that MetaXml needs for a file read off the filesystem.
        /// Copied from CodeWalker's ExploreForm.CreateFileEntry.</summary>
        public static RpfFileEntry CreateFileEntry(string name, string path, ref byte[] data)
        {
            RpfFileEntry e;
            uint rsc7 = (data != null && data.Length > 4) ? BitConverter.ToUInt32(data, 0) : 0;
            if (rsc7 == 0x37435352) // "RSC7" - resource file
            {
                e = RpfFile.CreateResourceFileEntry(ref data, 0);
                data = ResourceBuilder.Decompress(data);
            }
            else
            {
                var be = new RpfBinaryFileEntry();
                be.FileSize = (uint)(data != null ? data.Length : 0);
                be.FileUncompressedSize = be.FileSize;
                e = be;
            }
            e.Name = name;
            e.NameLower = name != null ? name.ToLowerInvariant() : null;
            e.NameHash = JenkHash.GenHash(e.NameLower);
            e.ShortNameHash = JenkHash.GenHash(Path.GetFileNameWithoutExtension(e.NameLower));
            e.Path = path;
            return e;
        }

        // ------------------------------------------------------------------ binary -> xml

        public static Dictionary<string, object> ToXml(JsonElement req)
        {
            var inPath = J.Path(req, "in");
            if (!File.Exists(inPath)) throw new FileNotFoundException("input not found: " + inPath);

            var name = Path.GetFileName(inPath);
            var data = File.ReadAllBytes(inPath);
            var entry = CreateFileEntry(name, inPath, ref data);

            var outPath = J.Str(req, "out");
            if (string.IsNullOrWhiteSpace(outPath)) outPath = inPath + ".xml";
            outPath = Path.GetFullPath(outPath);
            var outDir = Path.GetDirectoryName(outPath);
            if (!string.IsNullOrEmpty(outDir)) Directory.CreateDirectory(outDir);

            // Textures / embedded assets are written next to the xml, in a folder named
            // after the file with its extension stripped - the layout CodeWalker expects
            // when the xml is imported again.
            var assetDir = J.Str(req, "asset_dir");
            if (string.IsNullOrWhiteSpace(assetDir))
                assetDir = Path.Combine(outDir ?? ".", Path.GetFileNameWithoutExtension(name));
            assetDir = Path.GetFullPath(assetDir);

            string suggested;
            var xml = MetaXml.GetXml(entry, data, out suggested, assetDir);
            if (string.IsNullOrEmpty(xml))
                throw new InvalidOperationException(
                    "CodeWalker produced no XML for " + name + " - unsupported or corrupt file type.");

            File.WriteAllText(outPath, xml);

            var res = new Dictionary<string, object>
            {
                { "input", inPath },
                { "output", outPath },
                { "bytes_in", new FileInfo(inPath).Length },
                { "bytes_out", new FileInfo(outPath).Length },
                { "suggested_name", suggested },
                { "resource", entry is RpfResourceFileEntry },
            };
            if (Directory.Exists(assetDir))
            {
                var assets = Directory.GetFiles(assetDir);
                if (assets.Length > 0)
                {
                    res["asset_dir"] = assetDir;
                    res["asset_count"] = assets.Length;
                }
            }
            return res;
        }

        // ------------------------------------------------------------------ xml -> binary

        public static Dictionary<string, object> ToBin(JsonElement req)
        {
            var inPath = J.Path(req, "in");
            if (!File.Exists(inPath)) throw new FileNotFoundException("input not found: " + inPath);

            var name = Path.GetFileName(inPath);
            var namel = name.ToLowerInvariant();
            if (!namel.EndsWith(".xml"))
                throw new ArgumentException("input must be a .xml file (got " + name + ")");
            if (namel.IndexOf('.') == namel.LastIndexOf('.'))
                throw new ArgumentException(
                    "\"" + name + "\" is a plain .xml with no game-file extension; " +
                    "name it like foo.ytyp.xml / foo.ydr.xml so the format can be determined.");

            int trim;
            var format = XmlMeta.GetXMLFormat(namel, out trim);

            var outName = name.Substring(0, name.Length - trim);
            var outPath = J.Str(req, "out");
            if (string.IsNullOrWhiteSpace(outPath))
                outPath = Path.Combine(Path.GetDirectoryName(inPath) ?? ".", outName);
            outPath = Path.GetFullPath(outPath);
            var outDir = Path.GetDirectoryName(outPath);
            if (!string.IsNullOrEmpty(outDir)) Directory.CreateDirectory(outDir);

            // Where embedded textures are read from: <dir>\<name without extensions>
            var assetDir = J.Str(req, "asset_dir");
            if (string.IsNullOrWhiteSpace(assetDir))
            {
                var stem = inPath.Substring(0, inPath.Length - trim);          // ...\vb_int.ydr
                assetDir = Path.Combine(Path.GetDirectoryName(stem) ?? ".",
                                        Path.GetFileNameWithoutExtension(stem)); // ...\vb_int
            }
            assetDir = Path.GetFullPath(assetDir);

            var doc = new XmlDocument();
            var text = File.ReadAllText(inPath);
            if (string.IsNullOrEmpty(text)) throw new InvalidDataException("input xml is empty");
            doc.LoadXml(text);

            var data = XmlMeta.GetData(doc, format, assetDir);
            if (data == null)
                throw new InvalidOperationException(
                    "CodeWalker produced no data from " + name + " (format " +
                    XmlMeta.GetXMLFormatName(format) + "). The XML is probably missing " +
                    "required sections or has the wrong root element.");

            File.WriteAllBytes(outPath, data);

            return new Dictionary<string, object>
            {
                { "input", inPath },
                { "output", outPath },
                { "format", XmlMeta.GetXMLFormatName(format) },
                { "bytes_in", new FileInfo(inPath).Length },
                { "bytes_out", data.Length },
                { "asset_dir", Directory.Exists(assetDir) ? assetDir : null },
                { "rsc7", data.Length > 4 && BitConverter.ToUInt32(data, 0) == 0x37435352 },
            };
        }
    }
}
