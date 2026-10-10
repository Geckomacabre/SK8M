using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using CodeWalker.GameFiles;

namespace CWTool
{
    /// <summary>Builds a complete addon dlcpack (dlc.rpf with content.xml, setup2.xml and a
    /// nested assets RPF) so map files can be dropped straight into mods/update/x64/dlcpacks.</summary>
    public static class Dlc
    {
        const string AssetDirInDlc = "x64/levels/gta5";

        public static Dictionary<string, object> Create(JsonElement req)
        {
            var name = J.Req(req, "name").Trim().ToLowerInvariant();
            foreach (var ch in name)
            {
                if (!char.IsLetterOrDigit(ch) && ch != '_')
                    throw new ArgumentException(
                        "dlc name must be lowercase letters, digits and underscores only (got \"" + name + "\")");
            }

            var outDir = Path.GetFullPath(J.Req(req, "out_dir"));
            var packDir = Path.Combine(outDir, name);
            var dlcPath = Path.Combine(packDir, "dlc.rpf");
            var overwrite = J.Bool(req, "overwrite");
            var autoConvert = J.Bool(req, "auto_convert", true);
            var order = J.Int(req, "order", 21);

            if (File.Exists(dlcPath))
            {
                if (!overwrite)
                    throw new IOException("already exists: " + dlcPath +
                                          " (pass \"overwrite\": true to rebuild it)");
                File.Delete(dlcPath);
            }
            Directory.CreateDirectory(packDir);

            var files = J.Arr(req, "files");
            if (files == null) throw new ArgumentException("\"files\" must be an array");

            // ---------------------------------------------------------- sort the inputs
            var atDlcRoot = new List<Tuple<string, string, byte[], string>>();  // src, name, data, converted
            var inAssets = new List<Tuple<string, string, byte[], string>>();

            foreach (var item in files.Value.EnumerateArray())
            {
                string src, dest = null, where = null;
                if (item.ValueKind == JsonValueKind.String) src = item.GetString();
                else
                {
                    src = J.Str(item, "src");
                    dest = J.Str(item, "dest");
                    where = J.Str(item, "where");
                }
                if (string.IsNullOrWhiteSpace(src))
                    throw new ArgumentException("each entry in \"files\" needs a \"src\"");
                src = Path.GetFullPath(src);
                if (!File.Exists(src)) throw new FileNotFoundException("source not found: " + src);

                string suggested, converted;
                var data = Rpf.ReadForImport(src, autoConvert, out suggested, out converted);
                var entryName = string.IsNullOrWhiteSpace(dest) ? suggested : dest;

                // .ytyp must sit at the dlc.rpf root so DLC_ITYP_REQUEST can address it.
                bool root;
                if (!string.IsNullOrWhiteSpace(where))
                {
                    var w = where.Trim().ToLowerInvariant();
                    if (w == "dlc" || w == "root") root = true;
                    else if (w == "assets") root = false;
                    else throw new ArgumentException("\"where\" must be \"dlc\" or \"assets\" (got \"" + where + "\")");
                }
                else root = entryName.ToLowerInvariant().EndsWith(".ytyp");

                var rec = Tuple.Create(src, entryName, data, converted);
                if (root) atDlcRoot.Add(rec); else inAssets.Add(rec);
            }

            if (atDlcRoot.Count == 0)
                throw new ArgumentException(
                    "no .ytyp among the files - an MLO dlcpack needs one, and it must live at " +
                    "the dlc.rpf root so content.xml can reference it.");

            // ---------------------------------------------------------- build dlc.rpf
            var dlc = RpfFile.CreateNew(packDir, "dlc.rpf", RpfEncryption.OPEN);

            var contentXml = BuildContentXml(name, atDlcRoot);
            var setupXml = BuildSetupXml(name, order);
            RpfFile.CreateFile(dlc.Root, "content.xml", Encoding.UTF8.GetBytes(contentXml), true);
            RpfFile.CreateFile(dlc.Root, "setup2.xml", Encoding.UTF8.GetBytes(setupXml), true);

            var added = new List<Dictionary<string, object>>();
            foreach (var f in atDlcRoot)
            {
                RpfFile.CreateFile(dlc.Root, f.Item2, f.Item3, true);
                added.Add(Rec(f, name + "/dlc.rpf/" + f.Item2));
            }

            // Nested assets archive: dlc.rpf/x64/levels/gta5/<name>.rpf
            var assetsDir = Rpf.EnsureDir(dlc, AssetDirInDlc.Split('/'), 3, true);
            var assetsRpf = RpfFile.CreateNew(assetsDir, name + ".rpf", RpfEncryption.OPEN);
            foreach (var f in inAssets)
            {
                RpfFile.CreateFile(assetsRpf.Root, f.Item2, f.Item3, true);
                added.Add(Rec(f, name + "/dlc.rpf/" + AssetDirInDlc + "/" + name + ".rpf/" + f.Item2));
            }

            var readme = Path.Combine(packDir, "INSTALL.txt");
            File.WriteAllText(readme, BuildInstallNotes(name));

            return new Dictionary<string, object>
            {
                { "dlc_rpf", dlcPath },
                { "pack_dir", packDir },
                { "device_name", "dlc_" + name },
                { "change_set", name + "_AUTOGEN" },
                { "assets_rpf", AssetDirInDlc + "/" + name + ".rpf" },
                { "bytes", new FileInfo(dlcPath).Length },
                { "count", added.Count },
                { "added", added },
                { "install_notes", readme },
                { "install_to", "mods/update/x64/dlcpacks/" + name + "/dlc.rpf" },
            };
        }

        static Dictionary<string, object> Rec(Tuple<string, string, byte[], string> f, string dest)
        {
            var d = new Dictionary<string, object>
            {
                { "src", f.Item1 }, { "dest", dest }, { "bytes", f.Item3.Length },
            };
            if (f.Item4 != null) d["converted_from"] = f.Item4;
            return d;
        }

        // ------------------------------------------------------------------ templates

        static string BuildContentXml(string name, List<Tuple<string, string, byte[], string>> ytyps)
        {
            var dev = "dlc_" + name;
            var assetsPath = dev + ":/" + AssetDirInDlc + "/" + name + ".rpf";

            var dataFiles = new StringBuilder();
            var enable = new StringBuilder();

            dataFiles.Append(
                "    <Item>\n" +
                "      <filename>" + assetsPath + "</filename>\n" +
                "      <fileType>RPF_FILE</fileType>\n" +
                "      <overlay value=\"false\" />\n" +
                "      <disabled value=\"true\" />\n" +
                "      <persistent value=\"false\" />\n" +
                "    </Item>\n");
            enable.Append("        <Item>" + assetsPath + "</Item>\n");

            foreach (var y in ytyps)
            {
                if (!y.Item2.ToLowerInvariant().EndsWith(".ytyp")) continue;
                var p = dev + ":/" + y.Item2;
                dataFiles.Append(
                    "    <Item>\n" +
                    "      <filename>" + p + "</filename>\n" +
                    "      <fileType>DLC_ITYP_REQUEST</fileType>\n" +
                    "      <overlay value=\"false\" />\n" +
                    "      <disabled value=\"true\" />\n" +
                    "      <persistent value=\"false\" />\n" +
                    "    </Item>\n");
                enable.Append("        <Item>" + p + "</Item>\n");
            }

            return
"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
"<CDataFileMgr__ContentsOfDataFileXml>\n" +
"  <disabledFiles />\n" +
"  <includedXmlFiles />\n" +
"  <includedDataFiles />\n" +
"  <dataFiles>\n" +
dataFiles +
"  </dataFiles>\n" +
"  <contentChangeSets>\n" +
"    <Item>\n" +
"      <changeSetName>" + name + "_AUTOGEN</changeSetName>\n" +
"      <mapChangeSetData />\n" +
"      <filesToInvalidate />\n" +
"      <filesToDisable />\n" +
"      <filesToEnable>\n" +
enable +
"      </filesToEnable>\n" +
"      <txdToLoad />\n" +
"      <txdToUnload />\n" +
"      <residentResources />\n" +
"      <unregisterResources />\n" +
"      <executionConditions />\n" +
"    </Item>\n" +
"  </contentChangeSets>\n" +
"  <patchFiles />\n" +
"</CDataFileMgr__ContentsOfDataFileXml>\n";
        }

        static string BuildSetupXml(string name, int order)
        {
            return
"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
"<SSetupData>\n" +
"  <deviceName>dlc_" + name + "</deviceName>\n" +
"  <datFile>content.xml</datFile>\n" +
"  <timeStamp>" + DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss") + "</timeStamp>\n" +
"  <nameHash>" + name + "</nameHash>\n" +
"  <contentChangeSets />\n" +
"  <contentChangeSetGroups>\n" +
"    <Item>\n" +
"      <NameHash>GROUP_STARTUP</NameHash>\n" +
"      <ContentChangeSets>\n" +
"        <Item>" + name + "_AUTOGEN</Item>\n" +
"      </ContentChangeSets>\n" +
"    </Item>\n" +
"  </contentChangeSetGroups>\n" +
"  <startupScript />\n" +
"  <scriptCallstackSize value=\"0\" />\n" +
"  <type>EXTRACONTENT_COMPAT_PACK</type>\n" +
"  <order value=\"" + order + "\" />\n" +
"  <minorOrder value=\"0\" />\n" +
"  <isLevelPack value=\"false\" />\n" +
"  <dependencyPackHash />\n" +
"  <requiredVersion />\n" +
"  <subPackCount value=\"0\" />\n" +
"</SSetupData>\n";
        }

        static string BuildInstallNotes(string name)
        {
            return
"Addon dlcpack: " + name + "\n" +
"\n" +
"1. Copy this whole folder to:\n" +
"     <GTA V>\\mods\\update\\x64\\dlcpacks\\" + name + "\\\n" +
"   so that dlc.rpf ends up at\n" +
"     mods\\update\\x64\\dlcpacks\\" + name + "\\dlc.rpf\n" +
"\n" +
"2. Register it in dlclist.xml, inside\n" +
"     mods\\update\\update.rpf\\common\\data\\dlclist.xml\n" +
"   by adding this line to <Paths>:\n" +
"     <Item>dlcpacks:\\" + name + "\\</Item>\n" +
"\n" +
"3. Restart CodeWalker before checking the result - it caches ytyp archetypes\n" +
"   at startup, so a newly added ytyp is invisible until it restarts.\n" +
"\n" +
"Layout inside dlc.rpf:\n" +
"  content.xml                            - declares the ytyp and the assets rpf\n" +
"  setup2.xml                             - declares the change set (GROUP_STARTUP)\n" +
"  *.ytyp                                 - archetype definitions (must be at the root)\n" +
"  " + AssetDirInDlc + "/" + name + ".rpf   - ydr / ybn / ytd / ymap\n";
        }
    }
}
