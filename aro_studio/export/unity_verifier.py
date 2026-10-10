"""Unity 6 import verifier (Editor script) shipped inside every Unity package.

It is C# source held in a Python string so the exporter can write it into ``Editor/AroUnityVerifier.cs``. It has been
**syntax-checked with tree-sitter (see tests/test_unity_scripts.py) but has never been executed in Unity**: no Unity editor
is available where this project is built. Until ``docs/acceptance/evidence/unity/unity-verification.json`` exists, was produced
by this script in a real Unity 6 editor and passes ``aro_studio.verification.evidence.read_unity_evidence``, the Unity
import is reported BLOCKED, not PASS. See docs/verification/unity-verification-runbook.md.
"""

VERIFIER_CS = r"""// ARO 3D Studio - Unity 6 import verifier.  NOT YET EXECUTED IN UNITY (see docs/verification/unity-verification-runbook.md).
//
//   Unity -batchmode -projectPath <project> -executeMethod ARO.Studio.Editor.AroUnityVerifier.Run \
//         -aroPackage Assets/<slug>-Unity -aroReport <abs path>/unity-verification.json [-aroShots <abs dir>] -logFile verify.log -quit
//
// Do NOT pass -nographics if you want screenshots. Exit code: 0 = PASS, 1 = FAIL, 2 = PARTIAL (something not testable).
// Reads Metadata/unity_expectations.json (computed from the scene, independent of the glTF) and compares what Unity actually
// imported: scale, axes, handedness, parts/hierarchy, materials/textures, LODs (and camera-distance LOD switching), colliders,
// missing scripts, broken references and import errors.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using ARO.Studio;

namespace ARO.Studio.Editor
{
    public static class AroUnityVerifier
    {
        [Serializable] public class Check { public string name; public string status; public string detail; }
        [Serializable] public class Report
        {
            public int schema = 1;
            public string unityVersion, renderPipeline, gltfastVersion, packagePath, glbPath, prefabPath, checksumsSha256, overall, startedUtc;
            public List<Check> checks = new List<Check>();
            public List<string> importErrors = new List<string>();
            public List<string> importWarnings = new List<string>();
            public List<string> screenshots = new List<string>();
            public List<string> notVerified = new List<string>();
        }

        [Serializable] class PartExp { public string node, material; public int triangles; public float[] boundsMin, boundsMax; }
        [Serializable] class ColExp { public string node, kind, axis; public float[] center, size, boundsMin, boundsMax; public float radius, height; public int triangles; }
        [Serializable] class Tol { public float length_m; public float triangle_ratio; }
        [Serializable] class Expect
        {
            public float[] boundsMin, boundsMax, extents;
            public int triangles_lod0;
            public PartExp[] parts;
            public string[] materials;
            public ColExp[] colliders;
            public Tol tolerance;
        }
        [Serializable] class LodLevel { public int level; public float screenHeight; public int triangles; }
        [Serializable] class LodFile { public LodLevel[] levels; }

        static Report R;
        static Expect E;
        static float Tol1 = 0.01f;

        static string Arg(string name)
        {
            var a = Environment.GetCommandLineArgs();
            for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
            return null;
        }

        static void Add(string name, string status, string detail)
        {
            R.checks.Add(new Check { name = name, status = status, detail = detail });
            Debug.Log("[ARO-VERIFY] " + status + " " + name + " :: " + detail);
        }
        static void Pass(string n, string d) => Add(n, "PASS", d);
        static void Fail(string n, string d) => Add(n, "FAIL", d);
        static void NotTestable(string n, string d) => Add(n, "NOT_TESTABLE", d);
        static void Cond(bool ok, string n, string okDetail, string badDetail) { if (ok) Pass(n, okDetail); else Fail(n, badDetail); }

        // glTF (right-handed) -> Unity (left-handed, glTFast mirrors X)
        static Vector3 M(float[] a) => new Vector3(-a[0], a[1], a[2]);
        static Vector3 U(float[] a) => new Vector3(a[0], a[1], a[2]);

        public static void Run()
        {
            R = new Report { startedUtc = DateTime.UtcNow.ToString("o"), unityVersion = Application.unityVersion };
            var capture = new Application.LogCallback((msg, stack, type) =>
            {
                if (msg.StartsWith("[ARO-VERIFY]")) return;
                if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert) R.importErrors.Add(msg);
                else if (type == LogType.Warning) R.importWarnings.Add(msg);
            });
            Application.logMessageReceived += capture;
            int code = 1;
            try { Execute(); }
            catch (Exception e) { Fail("verifier ran to completion", e.GetType().Name + ": " + e.Message); }
            finally { Application.logMessageReceived -= capture; }

            R.overall = R.checks.Any(c => c.status == "FAIL") || R.checks.Count == 0 ? "FAIL"
                      : R.checks.Any(c => c.status == "NOT_TESTABLE") || R.notVerified.Count > 0 ? "PARTIAL" : "PASS";
            code = R.overall == "PASS" ? 0 : R.overall == "PARTIAL" ? 2 : 1;
            var reportPath = Arg("-aroReport") ?? "unity-verification.json";
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath)));
            File.WriteAllText(reportPath, JsonUtility.ToJson(R, true));
            Debug.Log("[ARO-VERIFY] overall " + R.overall + " -> " + reportPath);
            if (Application.isBatchMode) EditorApplication.Exit(code);
        }

        static void Execute()
        {
            var pkg = Arg("-aroPackage");
            if (string.IsNullOrEmpty(pkg)) { Fail("arguments", "-aroPackage Assets/<slug>-Unity is required"); return; }
            R.packagePath = pkg;
            R.renderPipeline = GraphicsSettings.currentRenderPipeline != null ? GraphicsSettings.currentRenderPipeline.GetType().Name : "Built-in";
            R.gltfastVersion = ReadGltfastVersion();
            if (R.gltfastVersion == null) Fail("glTFast installed", "com.unity.cloud.gltfast / com.atteneder.gltfast not found in Packages/manifest.json"); else Pass("glTFast installed", R.gltfastVersion);
            Cond(Application.unityVersion.StartsWith("6000."), "Unity 6 editor", Application.unityVersion, "Unity " + Application.unityVersion + " is not a Unity 6 (6000.x) editor");

            var abs = Path.GetFullPath(pkg);
            var sums = Path.Combine(abs, "Metadata", "checksums.sha256");
            if (File.Exists(sums)) R.checksumsSha256 = Sha256(File.ReadAllBytes(sums));
            E = JsonUtility.FromJson<Expect>(File.ReadAllText(Path.Combine(abs, "Metadata", "unity_expectations.json")));
            var lods = JsonUtility.FromJson<LodFile>(File.ReadAllText(Path.Combine(abs, "Metadata", "lods.json")));
            if (E.tolerance != null && E.tolerance.length_m > 0) Tol1 = E.tolerance.length_m;

            var glbs = Directory.GetFiles(Path.Combine(abs, "Models"), "*.glb");
            if (glbs.Length != 1) { Fail("exactly one Models/*.glb", glbs.Length + " found"); return; }
            var glb = pkg.TrimEnd('/') + "/Models/" + Path.GetFileName(glbs[0]);
            R.glbPath = glb;

            int errBefore = R.importErrors.Count;
            AssetDatabase.ImportAsset(glb, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(glb);
            if (model == null) { Fail("GLB imports as a GameObject", "AssetDatabase returned null (is glTFast installed and enabled for .glb?)"); return; }
            Pass("GLB imports as a GameObject", glb);

            // Build the prefab with the package's own importer, then verify the PREFAB (that is what a game uses).
            Selection.activeObject = model;
            try { AroAssetImporter.Build(); } catch (Exception e) { Fail("ARO > Build Vehicle Prefab runs", e.GetType().Name + ": " + e.Message); }
            var prefabPath = pkg.TrimEnd('/') + "/" + Path.GetFileNameWithoutExtension(glb) + ".prefab";
            R.prefabPath = prefabPath;
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            Cond(prefab != null, "prefab was written", prefabPath, "no prefab at " + prefabPath);
            if (prefab == null) return;
            var root = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            try
            {
                Cond(R.importErrors.Count == errBefore, "no import errors in the Console", "0 errors/exceptions logged during import", (R.importErrors.Count - errBefore) + " error(s): " + string.Join(" | ", R.importErrors.Skip(errBefore).Take(3)));
                CheckScaleAxesHandedness(root);
                CheckHierarchy(root);
                CheckMaterials(root);
                CheckLods(root, lods);
                CheckColliders(root);
                CheckReferences(root);
                Screenshots(root);
            }
            finally { UnityEngine.Object.DestroyImmediate(root); }
        }

        static string ReadGltfastVersion()
        {
            try
            {
                var m = File.ReadAllText(Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Packages", "manifest.json"));
                var r = Regex.Match(m, "\"(com\\.unity\\.cloud\\.gltfast|com\\.atteneder\\.gltfast)\"\\s*:\\s*\"([^\"]+)\"");
                return r.Success ? r.Groups[1].Value + "@" + r.Groups[2].Value : null;
            }
            catch (Exception) { return null; }
        }

        static string Sha256(byte[] b)
        {
            using (var h = System.Security.Cryptography.SHA256.Create())
                return string.Concat(h.ComputeHash(b).Select(x => x.ToString("x2")));
        }

        static Transform Find(Transform root, string name)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true)) if (t.name == name) return t;
            return null;
        }

        static bool UnderCollision(Transform t)
        {
            for (var p = t; p != null; p = p.parent) if (p.name == "Collision") return true;
            return false;
        }

        static IEnumerable<Renderer> VisualRenderers(GameObject root, int lod)
        {
            var suffix = "_LOD" + lod;
            return root.GetComponentsInChildren<Renderer>(true).Where(r => !UnderCollision(r.transform) && (r.name.EndsWith(suffix) || (lod == 0 && !Regex.IsMatch(r.name, "_LOD[0-9]+$"))));
        }

        static Bounds WorldBounds(IEnumerable<Renderer> rs)
        {
            Bounds b = default; bool first = true;
            foreach (var r in rs) { if (first) { b = r.bounds; first = false; } else b.Encapsulate(r.bounds); }
            return b;
        }

        static bool Near(Vector3 a, Vector3 b, float tol) => Vector3.Distance(a, b) <= tol;

        static void CheckScaleAxesHandedness(GameObject root)
        {
            var lod0 = VisualRenderers(root, 0).ToList();
            if (lod0.Count == 0) { Fail("LOD0 renderers found", "none under the prefab"); return; }
            var b = WorldBounds(lod0);
            var ext = U(E.extents);
            Cond(Near(b.size, ext, Tol1), "scale (size in metres)", "Unity bounds size " + b.size.ToString("F3") + " == expected " + ext.ToString("F3"), "Unity bounds size " + b.size.ToString("F3") + " != expected " + ext.ToString("F3") + " (tolerance " + Tol1 + " m)");
            // The expected box mirrored in X (glTFast convention) - this also verifies Y-up and Z-forward (axes would be permuted otherwise).
            var mn = M(E.boundsMax); var mx = M(E.boundsMin);
            var expMin = new Vector3(Mathf.Min(mn.x, mx.x), E.boundsMin[1], E.boundsMin[2]);
            var expMax = new Vector3(Mathf.Max(mn.x, mx.x), E.boundsMax[1], E.boundsMax[2]);
            Cond(Near(b.min, expMin, Tol1) && Near(b.max, expMax, Tol1), "orientation (+Y up, +Z forward, ground at Y=0)", "world bounds " + b.min.ToString("F3") + ".." + b.max.ToString("F3") + " match the expected frame", "world bounds " + b.min.ToString("F3") + ".." + b.max.ToString("F3") + " expected " + expMin.ToString("F3") + ".." + expMax.ToString("F3"));
            Cond(Mathf.Abs(b.min.y) <= Tol1, "origin on the ground plane", "min.y = " + b.min.y.ToString("F4"), "min.y = " + b.min.y.ToString("F4"));
            Cond(Near(root.transform.lossyScale, Vector3.one, 1e-4f), "root scale is 1", "lossyScale " + root.transform.lossyScale, "lossyScale " + root.transform.lossyScale);

            // Handedness: compare each part's centre with the X-mirrored expectation AND with the un-mirrored one.
            int asym = 0, okMirror = 0, okPlain = 0;
            foreach (var p in E.parts)
            {
                var cx = (p.boundsMin[0] + p.boundsMax[0]) * 0.5f;
                if (Mathf.Abs(cx) < 0.05f) continue; // centred parts cannot reveal a mirror
                var rs = lod0.Where(r => r.name == p.node || r.name == p.node + "_LOD0").ToList();
                if (rs.Count == 0) continue;
                asym++;
                var c = WorldBounds(rs).center;
                var ec = new Vector3((p.boundsMin[0] + p.boundsMax[0]) * 0.5f, (p.boundsMin[1] + p.boundsMax[1]) * 0.5f, (p.boundsMin[2] + p.boundsMax[2]) * 0.5f);
                if (Near(c, new Vector3(-ec.x, ec.y, ec.z), Tol1 * 2)) okMirror++;
                if (Near(c, ec, Tol1 * 2)) okPlain++;
            }
            if (asym == 0) NotTestable("handedness (left stays left)", "no part is off-centre in X, so a mirror error would be invisible; add left/right parts to make this testable");
            else Cond(okMirror == asym, "handedness (left stays left; glTFast X-mirror)", asym + "/" + asym + " off-centre parts sit at the X-mirrored position (plain, un-mirrored matches: " + okPlain + ")", okMirror + "/" + asym + " off-centre parts match the X-mirrored expectation (un-mirrored matches: " + okPlain + ") - sides are swapped or the convention differs");
        }

        static void CheckHierarchy(GameObject root)
        {
            var missing = new List<string>();
            foreach (var p in E.parts)
                if (Find(root.transform, p.node) == null && Find(root.transform, p.node + "_LOD0") == null) missing.Add(p.node);
            Cond(missing.Count == 0, "part names / hierarchy", E.parts.Length + " expected parts present by name", "missing parts: " + string.Join(", ", missing.Take(10)));
            if (E.colliders != null && E.colliders.Length > 0) Cond(Find(root.transform, "Collision") != null, "Collision group node", "present", "no 'Collision' node");
            var dup = root.GetComponentsInChildren<Transform>(true).GroupBy(t => t.parent == null ? "" : t.parent.GetInstanceID() + "/" + t.name).Count(g => g.Count() > 1);
            Cond(dup == 0, "no duplicate sibling names", "0 duplicates", dup + " duplicate sibling name(s)");
        }

        static void CheckMaterials(GameObject root)
        {
            var rs = VisualRenderers(root, 0).ToList();
            var bad = new List<string>(); var used = new HashSet<string>(); int textures = 0;
            foreach (var r in rs)
                foreach (var m in r.sharedMaterials)
                {
                    if (m == null) { bad.Add(r.name + ": null material"); continue; }
                    used.Add(Regex.Replace(m.name, @" \(Instance\)$", ""));
                    if (m.shader == null || m.shader.name == "Hidden/InternalErrorShader" || !m.shader.isSupported) bad.Add(r.name + ": " + m.name + " shader " + (m.shader == null ? "null" : m.shader.name));
                    foreach (var prop in new[] { "_BaseMap", "_MainTex", "baseColorTexture", "_BumpMap", "_MetallicGlossMap", "_OcclusionMap", "_EmissionMap" })
                        if (m.HasProperty(prop) && m.GetTexture(prop) != null) textures++;
                }
            Cond(bad.Count == 0, "materials resolve (no null / error shader)", used.Count + " materials, " + textures + " texture bindings", string.Join(" | ", bad.Take(5)));
            var absent = E.materials.Where(n => !used.Any(u => u == n || u.StartsWith(n))).ToList();
            Cond(absent.Count == 0, "all expected materials present", E.materials.Length + " expected, all found", "missing materials: " + string.Join(", ", absent.Take(10)));
        }

        static int TriCount(Renderer r)
        {
            var mf = r.GetComponent<MeshFilter>(); var smr = r as SkinnedMeshRenderer;
            var mesh = smr != null ? smr.sharedMesh : (mf != null ? mf.sharedMesh : null);
            if (mesh == null) return 0;
            long n = 0; for (int i = 0; i < mesh.subMeshCount; i++) n += mesh.GetIndexCount(i);
            return (int)(n / 3);
        }

        static void CheckLods(GameObject root, LodFile lods)
        {
            var g = root.GetComponent<LODGroup>();
            if (g == null) { Fail("LODGroup present", "none on the prefab root"); return; }
            var arr = g.GetLODs();
            Cond(arr.Length == lods.levels.Length, "LOD count", arr.Length + " levels", arr.Length + " levels, expected " + lods.levels.Length);
            var seen = new HashSet<Renderer>(); bool disjoint = true, decreasing = true; int prevTri = int.MaxValue; var tris = new List<int>();
            for (int i = 0; i < arr.Length; i++)
            {
                int t = arr[i].renderers.Where(r => r != null).Sum(TriCount); tris.Add(t);
                foreach (var r in arr[i].renderers) if (r != null && !seen.Add(r)) disjoint = false;
                if (t >= prevTri) decreasing = false; prevTri = t;
                var want = lods.levels.OrderBy(l => l.level).ElementAtOrDefault(i);
                if (want != null) Cond(t == want.triangles, "LOD" + i + " triangles", t + " == " + want.triangles, t + " != expected " + want.triangles);
                if (want != null) Cond(Mathf.Abs(arr[i].screenRelativeTransitionHeight - want.screenHeight) < 1e-3f, "LOD" + i + " transition height", arr[i].screenRelativeTransitionHeight.ToString("F3"), arr[i].screenRelativeTransitionHeight.ToString("F3") + " != " + want.screenHeight);
            }
            Cond(disjoint, "LOD levels use disjoint renderers", "no renderer appears in two levels", "a renderer is shared between LOD levels");
            Cond(decreasing, "triangle counts decrease with LOD", string.Join(" > ", tris), string.Join(", ", tris));
            // Switching: actually ask Unity which level a camera at distance d would show.
            var camGo = new GameObject("ARO_VerifyCam"); var cam = camGo.AddComponent<Camera>(); cam.fieldOfView = 60;
            try
            {
                var b = WorldBounds(VisualRenderers(root, 0)); var seq = new List<int>(); var ds = new[] { 4f, 10f, 20f, 40f, 80f, 160f, 320f };
                foreach (var d in ds)
                {
                    cam.transform.position = b.center + new Vector3(0, 1.5f, d); cam.transform.LookAt(b.center);
                    var info = LODUtility.CalculateVisualizationData(cam, g, -1);
                    seq.Add(info.activeLODLevel);
                }
                bool mono = true; for (int i = 1; i < seq.Count; i++) if (seq[i] != -1 && seq[i - 1] != -1 && seq[i] < seq[i - 1]) mono = false;
                bool nearIs0 = seq[0] == 0; bool changes = seq.Distinct().Count() > 1;
                Cond(mono && nearIs0 && changes, "LOD switching by camera distance", "distances " + string.Join(",", ds) + " -> levels " + string.Join(",", seq), "distances " + string.Join(",", ds) + " -> levels " + string.Join(",", seq) + " (must start at 0, never go back to a finer level, and change)");
            }
            finally { UnityEngine.Object.DestroyImmediate(camGo); }
        }

        static void CheckColliders(GameObject root)
        {
            if (E.colliders == null || E.colliders.Length == 0) { NotTestable("colliders", "the export declares no colliders"); return; }
            var col = Find(root.transform, "Collision");
            foreach (var ce in E.colliders)
            {
                var t = col != null ? Find(col, ce.node) : null;
                if (t == null) { Fail("collider " + ce.node, "node not found under Collision"); continue; }
                var c = t.GetComponent<Collider>();
                if (c == null) { Fail("collider " + ce.node, "node has no Collider component"); continue; }
                var kind = ce.kind;
                bool typeOk = kind == "box" ? c is BoxCollider : kind == "sphere" ? c is SphereCollider : kind == "capsule" ? c is CapsuleCollider : c is MeshCollider;
                if (!typeOk) { Fail("collider " + ce.node + " type", c.GetType().Name + " for kind " + kind); continue; }
                if (c is MeshCollider mc)
                {
                    bool ok = mc.sharedMesh != null && (kind == "mesh" || mc.convex);
                    int tri = mc.sharedMesh != null ? mc.sharedMesh.triangles.Length / 3 : 0;
                    bool within = kind == "mesh" || tri <= 255;
                    var detail = kind + ", " + tri + " triangles, convex=" + mc.convex;
                    Cond(ok && within, "collider " + ce.node + " mesh", detail, detail + " (needs a sharedMesh; convex colliders must be <= 255 triangles)");
                    if (ce.boundsMin != null)
                    {
                        var mn = M(ce.boundsMax); var mx = M(ce.boundsMin);
                        var emin = new Vector3(Mathf.Min(mn.x, mx.x), ce.boundsMin[1], ce.boundsMin[2]); var emax = new Vector3(Mathf.Max(mn.x, mx.x), ce.boundsMax[1], ce.boundsMax[2]);
                        var b = c.bounds;
                        Cond(Near(b.min, emin, Tol1 * 2) && Near(b.max, emax, Tol1 * 2), "collider " + ce.node + " dimensions/position", b.size.ToString("F3"), "bounds " + b.min.ToString("F3") + ".." + b.max.ToString("F3") + " expected " + emin.ToString("F3") + ".." + emax.ToString("F3"));
                    }
                }
                else if (c is BoxCollider bc && ce.size != null)
                {
                    var s = Vector3.Scale(bc.size, t.lossyScale); var wc = t.TransformPoint(bc.center);
                    Cond(Near(new Vector3(Mathf.Abs(s.x), Mathf.Abs(s.y), Mathf.Abs(s.z)), U(ce.size), Tol1) && Near(wc, M(ce.center), Tol1), "collider " + ce.node + " dimensions/position", "size " + s.ToString("F3") + " centre " + wc.ToString("F3"), "size " + s.ToString("F3") + " centre " + wc.ToString("F3") + " expected size " + U(ce.size).ToString("F3") + " centre " + M(ce.center).ToString("F3"));
                }
                else if (c is SphereCollider sc)
                {
                    var wc = t.TransformPoint(sc.center); var r = sc.radius * Mathf.Max(t.lossyScale.x, Mathf.Max(t.lossyScale.y, t.lossyScale.z));
                    Cond(Mathf.Abs(r - ce.radius) <= Tol1 && Near(wc, M(ce.center), Tol1), "collider " + ce.node + " dimensions/position", "r " + r.ToString("F3"), "r " + r.ToString("F3") + " centre " + wc.ToString("F3") + " expected r " + ce.radius + " centre " + M(ce.center).ToString("F3"));
                }
                else if (c is CapsuleCollider cc)
                {
                    var wc = t.TransformPoint(cc.center);
                    Cond(Mathf.Abs(cc.radius * t.lossyScale.x - ce.radius) <= Tol1 && Near(wc, M(ce.center), Tol1), "collider " + ce.node + " dimensions/position", "r " + cc.radius.ToString("F3") + " h " + cc.height.ToString("F3"), "r " + cc.radius.ToString("F3") + " centre " + wc.ToString("F3") + " expected r " + ce.radius + " centre " + M(ce.center).ToString("F3"));
                }
            }
        }

        static void CheckReferences(GameObject root)
        {
            int missingScripts = 0, broken = 0; var where = new List<string>();
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
            {
                missingScripts += GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(t.gameObject);
                foreach (var comp in t.GetComponents<Component>())
                {
                    if (comp == null) continue;
                    var so = new SerializedObject(comp); var it = so.GetIterator();
                    while (it.NextVisible(true))
                        if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue == null && it.objectReferenceInstanceIDValue != 0) { broken++; if (where.Count < 5) where.Add(t.name + "." + comp.GetType().Name + "." + it.propertyPath); }
                }
            }
            Cond(missingScripts == 0, "no missing scripts", "0", missingScripts + " missing script component(s)");
            Cond(broken == 0, "no broken object references", "0", broken + " broken reference(s): " + string.Join(", ", where));
            Cond(root.GetComponent<AroVehicleDescriptor>() != null, "AroVehicleDescriptor attached", "present", "descriptor component not found");
        }

        static void Screenshots(GameObject root)
        {
            var dir = Arg("-aroShots");
            if (string.IsNullOrEmpty(dir)) { R.notVerified.Add("screenshots not requested (-aroShots)"); return; }
            if (Application.isBatchMode && SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null) { R.notVerified.Add("screenshots impossible: batchmode with -nographics"); return; }
            Directory.CreateDirectory(dir);
            var b = WorldBounds(VisualRenderers(root, 0)); var camGo = new GameObject("ARO_ShotCam"); var cam = camGo.AddComponent<Camera>();
            var lightGo = new GameObject("ARO_ShotLight"); var l = lightGo.AddComponent<Light>(); l.type = LightType.Directional; lightGo.transform.rotation = Quaternion.Euler(50, -30, 0);
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(.92f, .92f, .92f);
            try
            {
                var views = new Dictionary<string, Vector3> { { "front", new Vector3(0, 0.15f, 1) }, { "side", new Vector3(1, 0.15f, 0) }, { "three_quarter", new Vector3(0.8f, 0.4f, 0.9f) } };
                foreach (var kv in views)
                {
                    cam.transform.position = b.center + kv.Value.normalized * b.size.magnitude * 1.4f; cam.transform.LookAt(b.center);
                    var rt = new RenderTexture(1024, 768, 24); cam.targetTexture = rt; cam.Render();
                    var prev = RenderTexture.active; RenderTexture.active = rt;
                    var tex = new Texture2D(1024, 768, TextureFormat.RGB24, false); tex.ReadPixels(new Rect(0, 0, 1024, 768), 0, 0); tex.Apply();
                    RenderTexture.active = prev; cam.targetTexture = null; UnityEngine.Object.DestroyImmediate(rt);
                    var p = Path.Combine(dir, kv.Key + ".png"); File.WriteAllBytes(p, tex.EncodeToPNG()); UnityEngine.Object.DestroyImmediate(tex); R.screenshots.Add(p);
                }
            }
            finally { UnityEngine.Object.DestroyImmediate(camGo); UnityEngine.Object.DestroyImmediate(lightGo); }
        }
    }
}
#endif
"""
