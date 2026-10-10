using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;

namespace CWTool
{
    /// <summary>
    /// Thin JSON-over-stdio wrapper around CodeWalker.Core.
    /// Reads one request object from stdin, writes one response object to stdout.
    /// Request:  {"cmd":"toxml", ...args}
    /// Response: {"ok":true, ...} | {"ok":false,"error":"..."}
    /// </summary>
    public static class Program
    {
        public static int Main(string[] argv)
        {
            Console.OutputEncoding = new UTF8Encoding(false);

            string raw;
            if (argv.Length >= 2 && argv[0] == "--json") raw = argv[1];
            else raw = Console.In.ReadToEnd();

            if (string.IsNullOrWhiteSpace(raw))
            {
                Write(Err("empty request; expected a JSON object on stdin"));
                return 1;
            }

            JsonElement req;
            try
            {
                req = JsonDocument.Parse(raw).RootElement;
            }
            catch (Exception ex)
            {
                Write(Err("request is not valid JSON: " + ex.Message));
                return 1;
            }

            var cmd = J.Str(req, "cmd");
            if (string.IsNullOrEmpty(cmd))
            {
                Write(Err("missing \"cmd\""));
                return 1;
            }

            Names.Seed(req);

            Dictionary<string, object> res;
            try
            {
                switch (cmd)
                {
                    case "toxml":       res = Convert2.ToXml(req); break;
                    case "tobin":       res = Convert2.ToBin(req); break;
                    case "info":        res = Inspect.Info(req); break;
                    case "mlo_validate":res = Inspect.MloValidate(req); break;
                    case "hash":        res = Inspect.Hash(req); break;

                    case "rpf_create":  res = Rpf.Create(req); break;
                    case "rpf_add":     res = Rpf.Add(req); break;
                    case "rpf_list":    res = Rpf.List(req); break;
                    case "rpf_extract": res = Rpf.Extract(req); break;
                    case "rpf_delete":  res = Rpf.Delete(req); break;
                    case "pack":        res = Rpf.Pack(req); break;

                    case "dlc_create":  res = Dlc.Create(req); break;

                    default:
                        Write(Err("unknown cmd \"" + cmd + "\""));
                        return 1;
                }
            }
            catch (Exception ex)
            {
                var e = Err(ex.Message);
                e["exception"] = ex.GetType().Name;
                e["trace"] = (ex.StackTrace ?? "").Split('\n')[0].Trim();
                if (ex.InnerException != null) e["inner"] = ex.InnerException.Message;
                Write(e);
                return 1;
            }

            res["ok"] = true;
            Write(res);
            return 0;
        }

        static Dictionary<string, object> Err(string msg)
        {
            return new Dictionary<string, object> { { "ok", false }, { "error", msg } };
        }

        static void Write(Dictionary<string, object> obj)
        {
            var opts = new JsonSerializerOptions { WriteIndented = true };
            Console.Out.Write(JsonSerializer.Serialize(obj, opts));
            Console.Out.Flush();
        }
    }

    /// <summary>JsonElement accessors that tolerate missing / wrongly-typed fields.</summary>
    public static class J
    {
        public static string Str(JsonElement e, string name, string dflt = null)
        {
            JsonElement v;
            if (!e.TryGetProperty(name, out v)) return dflt;
            if (v.ValueKind == JsonValueKind.Null) return dflt;
            return v.ValueKind == JsonValueKind.String ? v.GetString() : v.ToString();
        }

        public static bool Bool(JsonElement e, string name, bool dflt = false)
        {
            JsonElement v;
            if (!e.TryGetProperty(name, out v)) return dflt;
            if (v.ValueKind == JsonValueKind.True) return true;
            if (v.ValueKind == JsonValueKind.False) return false;
            return dflt;
        }

        public static int Int(JsonElement e, string name, int dflt = 0)
        {
            JsonElement v;
            if (!e.TryGetProperty(name, out v)) return dflt;
            int i;
            if (v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out i)) return i;
            if (v.ValueKind == JsonValueKind.String && int.TryParse(v.GetString(), out i)) return i;
            return dflt;
        }

        public static JsonElement? Arr(JsonElement e, string name)
        {
            JsonElement v;
            if (!e.TryGetProperty(name, out v)) return null;
            if (v.ValueKind != JsonValueKind.Array) return null;
            return v;
        }

        /// <summary>Required string field; throws with a useful message when absent.</summary>
        public static string Req(JsonElement e, string name)
        {
            var s = Str(e, name);
            if (string.IsNullOrWhiteSpace(s))
                throw new ArgumentException("missing required field \"" + name + "\"");
            return s;
        }

        public static string Path(JsonElement e, string name)
        {
            return System.IO.Path.GetFullPath(Req(e, name));
        }
    }
}
