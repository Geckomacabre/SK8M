using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using CodeWalker.GameFiles;
using SharpDX;

namespace CWTool
{
    /// <summary>Typed inspection of game files, plus MLO cross-file consistency checks.</summary>
    public static class Inspect
    {
        // ------------------------------------------------------------------ small helpers

        static object V3(Vector3 v)
        {
            return new Dictionary<string, object>
            {
                { "x", Math.Round(v.X, 4) }, { "y", Math.Round(v.Y, 4) }, { "z", Math.Round(v.Z, 4) },
            };
        }

        static bool Degenerate(Vector3 min, Vector3 max)
        {
            return max.X - min.X <= 0.0001f || max.Y - min.Y <= 0.0001f || max.Z - min.Z <= 0.0001f;
        }

        static byte[] LoadRaw(string path, out RpfFileEntry entry)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("not found: " + path);
            var data = File.ReadAllBytes(path);
            entry = Convert2.CreateFileEntry(Path.GetFileName(path), path, ref data);
            return data;
        }

        public static YtypFile LoadYtyp(string path)
        {
            RpfFileEntry e;
            var data = LoadRaw(path, out e);
            var y = new YtypFile();
            y.Load(data, e);
            return y;
        }

        public static YmapFile LoadYmap(string path)
        {
            RpfFileEntry e;
            var data = LoadRaw(path, out e);
            var y = new YmapFile();
            y.Load(data, e);
            return y;
        }

        public static YdrFile LoadYdr(string path)
        {
            RpfFileEntry e;
            var data = LoadRaw(path, out e);
            var y = new YdrFile();
            y.Load(data, e);
            return y;
        }

        public static YbnFile LoadYbn(string path)
        {
            RpfFileEntry e;
            var data = LoadRaw(path, out e);
            var y = new YbnFile();
            y.Load(data, e);
            return y;
        }

        // ------------------------------------------------------------------ hash

        public static Dictionary<string, object> Hash(JsonElement req)
        {
            var text = J.Req(req, "text");
            var h = JenkHash.GenHash(text.ToLowerInvariant());
            return new Dictionary<string, object>
            {
                { "text", text },
                { "hash", h },
                { "hex", h.ToString("X8") },
                { "hash_cased", JenkHash.GenHash(text) },
            };
        }

        // ------------------------------------------------------------------ info

        public static Dictionary<string, object> Info(JsonElement req)
        {
            var path = J.Path(req, "in");
            var ext = Path.GetExtension(path).ToLowerInvariant();

            var res = new Dictionary<string, object>
            {
                { "file", path },
                { "bytes", new FileInfo(path).Length },
                { "type", ext.TrimStart('.') },
            };

            switch (ext)
            {
                case ".ytyp": res["ytyp"] = YtypInfo(LoadYtyp(path), J.Bool(req, "full")); break;
                case ".ymap": res["ymap"] = YmapInfo(LoadYmap(path)); break;
                case ".ydr":  res["ydr"]  = YdrInfo(LoadYdr(path)); break;
                case ".ybn":  res["ybn"]  = YbnInfo(LoadYbn(path)); break;
                default:
                    throw new ArgumentException(
                        "info supports .ytyp, .ymap, .ydr and .ybn (got \"" + ext + "\"). " +
                        "Use toxml for anything else.");
            }
            return res;
        }

        static Dictionary<string, object> YtypInfo(YtypFile ytyp, bool full)
        {
            var archs = new List<Dictionary<string, object>>();
            foreach (var a in ytyp.AllArchetypes ?? new Archetype[0])
            {
                var d = new Dictionary<string, object>
                {
                    { "name", a.Name },
                    { "type", a.Type.ToString() },
                    { "asset_name", a.AssetName },
                    { "texture_dict", a.TextureDict.ToString() },
                    { "drawable_dict", a.DrawableDict.ToString() },
                    { "physics_dict", a._BaseArchetypeDef.physicsDictionary.ToString() },
                    { "lod_dist", a.LodDist },
                    { "flags", a._BaseArchetypeDef.flags },
                    { "bb_min", V3(a.BBMin) },
                    { "bb_max", V3(a.BBMax) },
                    { "bs_centre", V3(a.BSCenter) },
                    { "bs_radius", Math.Round(a.BSRadius, 4) },
                };

                var mlo = a as MloArchetype;
                if (mlo != null)
                {
                    d["mlo_flags"] = mlo._MloArchetypeDefData.mloFlags;
                    d["room_count"] = mlo.rooms != null ? mlo.rooms.Length : 0;
                    d["portal_count"] = mlo.portals != null ? mlo.portals.Length : 0;
                    d["entity_count"] = mlo.entities != null ? mlo.entities.Length : 0;
                    d["entity_set_count"] = mlo.entitySets != null ? mlo.entitySets.Length : 0;

                    if (full)
                    {
                        var rooms = new List<Dictionary<string, object>>();
                        for (int i = 0; i < (mlo.rooms ?? new MCMloRoomDef[0]).Length; i++)
                        {
                            var r = mlo.rooms[i];
                            rooms.Add(new Dictionary<string, object>
                            {
                                { "index", i },
                                { "name", r.RoomName },
                                { "bb_min", V3(r.BBMin) },
                                { "bb_max", V3(r.BBMax) },
                                { "flags", r._Data.flags },
                                { "portal_count", r._Data.portalCount },
                                { "floor_id", r._Data.floorId },
                                { "attached_objects", r.AttachedObjects != null ? r.AttachedObjects.Length : 0 },
                            });
                        }
                        d["rooms"] = rooms;

                        var portals = new List<Dictionary<string, object>>();
                        for (int i = 0; i < (mlo.portals ?? new MCMloPortalDef[0]).Length; i++)
                        {
                            var p = mlo.portals[i];
                            portals.Add(new Dictionary<string, object>
                            {
                                { "index", i },
                                { "room_from", p._Data.roomFrom },
                                { "room_to", p._Data.roomTo },
                                { "corners", p.Corners != null ? p.Corners.Length : 0 },
                                { "flags", p._Data.flags },
                                { "opacity", p._Data.opacity },
                                { "attached_objects", p.AttachedObjects != null ? p.AttachedObjects.Length : 0 },
                            });
                        }
                        d["portals"] = portals;
                    }
                }
                archs.Add(d);
            }

            return new Dictionary<string, object>
            {
                { "name", new MetaHash(ytyp.NameHash).ToString() },
                { "archetype_count", archs.Count },
                { "archetypes", archs },
            };
        }

        static Dictionary<string, object> YmapInfo(YmapFile ymap)
        {
            var ents = new List<Dictionary<string, object>>();
            foreach (var e in ymap.AllEntities ?? new YmapEntityDef[0])
            {
                ents.Add(new Dictionary<string, object>
                {
                    { "archetype", e._CEntityDef.archetypeName.ToString() },
                    { "position", V3(e.Position) },
                    { "rotation", new Dictionary<string, object>
                        {
                            { "x", Math.Round(e.Orientation.X, 6) }, { "y", Math.Round(e.Orientation.Y, 6) },
                            { "z", Math.Round(e.Orientation.Z, 6) }, { "w", Math.Round(e.Orientation.W, 6) },
                        } },
                    { "flags", e._CEntityDef.flags },
                    { "lod_dist", e._CEntityDef.lodDist },
                    { "lod_level", e._CEntityDef.lodLevel.ToString() },
                    { "is_mlo", e.IsMlo },
                });
            }

            return new Dictionary<string, object>
            {
                { "name", ymap._CMapData.name.ToString() },
                { "parent", ymap._CMapData.parent.ToString() },
                { "flags", ymap._CMapData.flags },
                { "content_flags", ymap._CMapData.contentFlags },
                { "entity_count", ents.Count },
                { "mlo_instance_count", ymap.CMloInstanceDefs != null ? ymap.CMloInstanceDefs.Length : 0 },
                { "car_generators", ymap.CarGenerators != null ? ymap.CarGenerators.Length : 0 },
                { "entities_extents_min", V3(ymap._CMapData.entitiesExtentsMin) },
                { "entities_extents_max", V3(ymap._CMapData.entitiesExtentsMax) },
                { "streaming_extents_min", V3(ymap._CMapData.streamingExtentsMin) },
                { "streaming_extents_max", V3(ymap._CMapData.streamingExtentsMax) },
                { "entities", ents },
            };
        }

        static Dictionary<string, object> YdrInfo(YdrFile ydr)
        {
            var d = ydr.Drawable;
            if (d == null) throw new InvalidDataException("ydr contains no drawable");

            var shaders = new List<string>();
            if (d.ShaderGroup != null && d.ShaderGroup.Shaders != null &&
                d.ShaderGroup.Shaders.data_items != null)
            {
                foreach (var s in d.ShaderGroup.Shaders.data_items)
                    if (s != null) shaders.Add(s.Name.ToString());
            }

            var textures = new List<string>();
            var td = d.ShaderGroup != null ? d.ShaderGroup.TextureDictionary : null;
            if (td != null && td.Textures != null && td.Textures.data_items != null)
            {
                foreach (var t in td.Textures.data_items)
                    if (t != null) textures.Add(t.Name);
            }

            int geomCount = 0, vertCount = 0, triCount = 0;
            foreach (var m in d.AllModels ?? new DrawableModel[0])
            {
                if (m == null || m.Geometries == null) continue;
                foreach (var g in m.Geometries)
                {
                    if (g == null) continue;
                    geomCount++;
                    if (g.VertexData != null) vertCount += g.VertexData.VertexCount;
                    if (g.IndexBuffer != null && g.IndexBuffer.IndicesCount > 0)
                        triCount += (int)(g.IndexBuffer.IndicesCount / 3);
                }
            }

            return new Dictionary<string, object>
            {
                { "name", d.Name },
                { "bb_min", V3(d.BoundingBoxMin) },
                { "bb_max", V3(d.BoundingBoxMax) },
                { "bs_centre", V3(d.BoundingCenter) },
                { "bs_radius", Math.Round(d.BoundingSphereRadius, 4) },
                { "lod_dist_high", d.LodDistHigh },
                { "models_high", d.DrawableModels != null && d.DrawableModels.High != null
                                    ? d.DrawableModels.High.Length : 0 },
                { "models_total", d.AllModels != null ? d.AllModels.Length : 0 },
                { "geometry_count", geomCount },
                { "vertex_count", vertCount },
                { "triangle_count", triCount },
                { "shader_count", shaders.Count },
                { "shaders", shaders },
                { "embedded_texture_count", textures.Count },
                { "embedded_textures", textures },
                { "has_bound", d.Bound != null },
            };
        }

        static Dictionary<string, object> YbnInfo(YbnFile ybn)
        {
            var b = ybn.Bounds;
            if (b == null) throw new InvalidDataException("ybn contains no bounds");

            var res = new Dictionary<string, object>
            {
                { "type", b.Type.ToString() },
                { "box_min", V3(b.BoxMin) },
                { "box_max", V3(b.BoxMax) },
                { "sphere_radius", Math.Round(b.SphereRadius, 4) },
                { "margin", Math.Round(b.Margin, 4) },
            };

            var children = new List<Dictionary<string, object>>();
            var comp = b as BoundComposite;
            if (comp != null && comp.Children != null && comp.Children.data_items != null)
            {
                foreach (var c in comp.Children.data_items)
                {
                    if (c == null) continue;
                    children.Add(DescribeBound(c));
                }
            }
            else
            {
                children.Add(DescribeBound(b));
            }
            res["child_count"] = children.Count;
            res["children"] = children;
            return res;
        }

        static Dictionary<string, object> DescribeBound(Bounds b)
        {
            var d = new Dictionary<string, object>
            {
                { "type", b.Type.ToString() },
                { "box_min", V3(b.BoxMin) },
                { "box_max", V3(b.BoxMax) },
            };
            var geom = b as BoundGeometry;
            if (geom != null)
            {
                d["polygons"] = geom.Polygons != null ? geom.Polygons.Length : 0;
                d["vertices"] = geom.Vertices != null ? geom.Vertices.Length : 0;
                d["materials"] = geom.Materials != null ? geom.Materials.Length : 0;
            }
            return d;
        }

        // ------------------------------------------------------------------ mlo_validate

        /// <summary>Cross-check an MLO's ytyp against its ymap, drawable and collision.
        /// This is aimed squarely at the failure modes that make an interior render as
        /// nothing at all in game: zeroed archetype bounds, a ymap pointing at an
        /// archetype name that no ytyp defines, and portals indexing rooms that
        /// do not exist.</summary>
        public static Dictionary<string, object> MloValidate(JsonElement req)
        {
            var ytypPath = J.Path(req, "ytyp");
            var archName = J.Str(req, "archetype");

            var errors = new List<string>();
            var warnings = new List<string>();
            var notes = new List<string>();

            var ytyp = LoadYtyp(ytypPath);
            var all = ytyp.AllArchetypes ?? new Archetype[0];
            if (all.Length == 0) errors.Add("ytyp defines no archetypes at all");

            MloArchetype mlo = null;
            foreach (var a in all)
            {
                var m = a as MloArchetype;
                if (m == null) continue;
                if (archName == null || string.Equals(m.Name, archName, StringComparison.OrdinalIgnoreCase))
                { mlo = m; break; }
            }
            if (mlo == null)
                throw new InvalidDataException(archName == null
                    ? "no CMloArchetypeDef found in " + ytypPath
                    : "no MLO archetype named \"" + archName + "\" in " + ytypPath);

            var bd = mlo._BaseArchetypeDef;

            // --- archetype header ------------------------------------------------
            if (Degenerate(mlo.BBMin, mlo.BBMax))
                errors.Add("archetype bounding box is zero/degenerate - the interior will not stream in. " +
                           "bbMin=" + mlo.BBMin + " bbMax=" + mlo.BBMax);
            if (mlo.BSRadius <= 0.0001f)
                errors.Add("archetype bsRadius is 0 - the interior will not stream in.");
            else
            {
                var half = (mlo.BBMax - mlo.BBMin) * 0.5f;
                var need = half.Length();
                if (mlo.BSRadius < need * 0.99f)
                    warnings.Add("bsRadius " + Math.Round(mlo.BSRadius, 3) +
                                 " is smaller than the bounding box half-diagonal " +
                                 Math.Round(need, 3) + "; parts may pop out at range.");
            }
            if (bd.lodDist <= 0)
                warnings.Add("archetype lodDist is " + bd.lodDist + "; set it to the distance " +
                             "at which the interior should start streaming (600 is typical).");
            if (string.IsNullOrEmpty(mlo.AssetName) || mlo.AssetName == "0")
                errors.Add("archetype has no assetName - nothing tells the game which drawable to draw.");

            // --- rooms -----------------------------------------------------------
            var rooms = mlo.rooms ?? new MCMloRoomDef[0];
            if (rooms.Length == 0) errors.Add("archetype has no rooms");
            else if (!string.Equals(rooms[0].RoomName, "limbo", StringComparison.OrdinalIgnoreCase))
                warnings.Add("room 0 is \"" + rooms[0].RoomName + "\", not \"limbo\"; " +
                             "the game treats room 0 as the exterior/limbo room.");

            var portals = mlo.portals ?? new MCMloPortalDef[0];
            var portalsPerRoom = new int[rooms.Length];

            for (int i = 0; i < rooms.Length; i++)
            {
                var r = rooms[i];
                if (string.IsNullOrWhiteSpace(r.RoomName))
                    errors.Add("room " + i + " has no name");
                if (i > 0 && Degenerate(r.BBMin, r.BBMax))
                    errors.Add("room " + i + " \"" + r.RoomName + "\" has a zero/degenerate bounding box");
                foreach (var ao in r.AttachedObjects ?? new uint[0])
                {
                    var n = mlo.entities != null ? mlo.entities.Length : 0;
                    if (ao >= n)
                        errors.Add("room " + i + " \"" + r.RoomName + "\" attaches entity " + ao +
                                   " but the archetype only has " + n + " entities");
                }
            }

            // --- portals ---------------------------------------------------------
            for (int i = 0; i < portals.Length; i++)
            {
                var p = portals[i];
                if (p._Data.roomFrom >= rooms.Length)
                    errors.Add("portal " + i + " roomFrom=" + p._Data.roomFrom +
                               " is out of range (" + rooms.Length + " rooms)");
                else portalsPerRoom[p._Data.roomFrom]++;

                if (p._Data.roomTo >= rooms.Length)
                    errors.Add("portal " + i + " roomTo=" + p._Data.roomTo +
                               " is out of range (" + rooms.Length + " rooms)");
                else portalsPerRoom[p._Data.roomTo]++;

                if (p._Data.roomFrom == p._Data.roomTo)
                    warnings.Add("portal " + i + " joins room " + p._Data.roomFrom + " to itself");

                var nc = p.Corners != null ? p.Corners.Length : 0;
                if (nc != 4)
                    errors.Add("portal " + i + " has " + nc + " corners; the game requires exactly 4");
            }

            for (int i = 0; i < rooms.Length; i++)
            {
                if (rooms[i]._Data.portalCount != (uint)portalsPerRoom[i])
                    warnings.Add("room " + i + " \"" + rooms[i].RoomName + "\" declares portalCount=" +
                                 rooms[i]._Data.portalCount + " but " + portalsPerRoom[i] +
                                 " portals actually reference it");
                if (i > 0 && portalsPerRoom[i] == 0)
                    warnings.Add("room " + i + " \"" + rooms[i].RoomName +
                                 "\" has no portals - it is unreachable and will not render.");
            }

            var result = new Dictionary<string, object>
            {
                { "ytyp", ytypPath },
                { "archetype", mlo.Name },
                { "asset_name", mlo.AssetName },
                { "rooms", rooms.Length },
                { "portals", portals.Length },
                { "entities", mlo.entities != null ? mlo.entities.Length : 0 },
                { "bb_min", V3(mlo.BBMin) },
                { "bb_max", V3(mlo.BBMax) },
                { "bs_radius", Math.Round(mlo.BSRadius, 4) },
                { "lod_dist", bd.lodDist },
                { "flags", bd.flags },
                { "mlo_flags", mlo._MloArchetypeDefData.mloFlags },
            };

            // --- ymap ------------------------------------------------------------
            var ymapPath = J.Str(req, "ymap");
            if (!string.IsNullOrWhiteSpace(ymapPath))
            {
                ymapPath = Path.GetFullPath(ymapPath);
                var ymap = LoadYmap(ymapPath);
                result["ymap"] = ymapPath;

                var insts = ymap.CMloInstanceDefs ?? new CMloInstanceDef[0];
                result["ymap_mlo_instances"] = insts.Length;

                if (insts.Length == 0)
                    errors.Add("ymap contains no CMloInstanceDef - nothing places the interior in the world");

                bool found = false;
                foreach (var inst in insts)
                {
                    var an = inst.CEntityDef.archetypeName;
                    if (an.Hash == bd.name.Hash) { found = true; break; }
                }
                if (insts.Length > 0 && !found)
                {
                    var names = insts.Select(i => i.CEntityDef.archetypeName.ToString()).ToArray();
                    errors.Add("no CMloInstanceDef in the ymap references archetype \"" + mlo.Name +
                               "\" (hash " + bd.name.Hash.ToString("X8") + "). ymap references: " +
                               string.Join(", ", names));
                }

                foreach (var e in ymap.AllEntities ?? new YmapEntityDef[0])
                {
                    if (e._CEntityDef.lodDist <= 0)
                        warnings.Add("ymap entity \"" + e._CEntityDef.archetypeName +
                                     "\" has lodDist " + e._CEntityDef.lodDist);
                }

                var eMin = ymap._CMapData.entitiesExtentsMin;
                var eMax = ymap._CMapData.entitiesExtentsMax;
                if (Degenerate(eMin, eMax))
                    warnings.Add("ymap entitiesExtents are zero/degenerate; the game may cull the map file.");

                if (ymap._CMapData.contentFlags == 0)
                    warnings.Add("ymap contentFlags is 0; an MLO-bearing ymap normally sets it (9 is typical).");
            }
            else notes.Add("no ymap given - placement was not checked");

            // --- drawable --------------------------------------------------------
            var ydrPath = J.Str(req, "ydr");
            if (!string.IsNullOrWhiteSpace(ydrPath))
            {
                ydrPath = Path.GetFullPath(ydrPath);
                var ydr = LoadYdr(ydrPath);
                result["ydr"] = ydrPath;

                var expect = Path.GetFileNameWithoutExtension(ydrPath);
                if (!string.Equals(expect, mlo.AssetName, StringComparison.OrdinalIgnoreCase))
                    errors.Add("drawable file is named \"" + expect + ".ydr\" but the archetype's assetName is \"" +
                               mlo.AssetName + "\"; the game looks the drawable up by assetName.");

                var d = ydr.Drawable;
                if (d == null) errors.Add("ydr has no drawable");
                else
                {
                    result["ydr_bb_min"] = V3(d.BoundingBoxMin);
                    result["ydr_bb_max"] = V3(d.BoundingBoxMax);

                    // Archetype bounds must cover the drawable, else parts get culled.
                    var dmin = d.BoundingBoxMin; var dmax = d.BoundingBoxMax;
                    const float tol = 0.05f;
                    if (dmin.X < mlo.BBMin.X - tol || dmin.Y < mlo.BBMin.Y - tol || dmin.Z < mlo.BBMin.Z - tol ||
                        dmax.X > mlo.BBMax.X + tol || dmax.Y > mlo.BBMax.Y + tol || dmax.Z > mlo.BBMax.Z + tol)
                        errors.Add("the drawable sticks out of the archetype bounding box " +
                                   "(drawable " + dmin + " .. " + dmax + " vs archetype " +
                                   mlo.BBMin + " .. " + mlo.BBMax + "); the overhang will be culled.");

                    int geom = 0;
                    foreach (var m in d.AllModels ?? new DrawableModel[0])
                        if (m != null && m.Geometries != null) geom += m.Geometries.Length;
                    result["ydr_geometries"] = geom;
                    if (geom == 0) errors.Add("drawable has no geometry");
                }
            }
            else notes.Add("no ydr given - the drawable was not checked");

            // --- collision -------------------------------------------------------
            var ybnPath = J.Str(req, "ybn");
            if (!string.IsNullOrWhiteSpace(ybnPath))
            {
                ybnPath = Path.GetFullPath(ybnPath);
                var ybn = LoadYbn(ybnPath);
                result["ybn"] = ybnPath;

                if (ybn.Bounds == null) errors.Add("ybn has no bounds");
                else
                {
                    result["ybn_box_min"] = V3(ybn.Bounds.BoxMin);
                    result["ybn_box_max"] = V3(ybn.Bounds.BoxMax);
                }

                var pd = bd.physicsDictionary;
                var stem = Path.GetFileNameWithoutExtension(ybnPath);
                if (pd.Hash == 0)
                    warnings.Add("archetype physicsDictionary is empty; collision is usually resolved " +
                                 "by it (expected something like \"" + stem + "\").");
            }
            else notes.Add("no ybn given - collision was not checked");

            result["errors"] = errors;
            result["warnings"] = warnings;
            result["notes"] = notes;
            result["error_count"] = errors.Count;
            result["warning_count"] = warnings.Count;
            result["verdict"] = errors.Count == 0
                ? (warnings.Count == 0 ? "PASS" : "PASS with warnings")
                : "FAIL";
            return result;
        }
    }
}
