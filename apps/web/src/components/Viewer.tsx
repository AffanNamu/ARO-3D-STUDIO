"use client";
import { Bounds, ContactShadows, Grid, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Component, Suspense, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { formatSize, isVisible, lodLevels, roleOf, type MeshRole } from "@/lib/model";

type Mode = "textured" | "clay" | "wire";
type Light = "studio" | "outdoor" | "soft";
type Info = { levels: number[]; hasCollision: boolean; triangles: number; size: [number, number, number] };
type Entry = { mesh: THREE.Mesh; role: MeshRole; original: THREE.Material | THREE.Material[] };

const CLAY = new THREE.MeshStandardMaterial({ color: "#c9ccd3", roughness: 0.85, metalness: 0 });
const COLLISION = new THREE.MeshBasicMaterial({ color: "#3ecf8e", wireframe: true, transparent: true, opacity: 0.75 });

function Model({ url, mode, level, showCollision, onInfo }: { url: string; mode: Mode; level: number | null; showCollision: boolean; onInfo: (i: Info) => void }) {
  // no Draco or Meshopt decoders: our GLBs use neither, and both would need WebAssembly (blocked by the page's CSP) or a third-party CDN
  const gltf = useGLTF(url, false, false);
  const { scene, entries, levels, hasCollision } = useMemo(() => {
    const root = gltf.scene.clone(true);
    const list: Entry[] = [];
    root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const names: string[] = [];
      for (let p: THREE.Object3D | null = m; p; p = p.parent) names.push(p.name);
      // each view owns its materials, so a wireframe toggle never leaks into the loader's cache
      m.material = Array.isArray(m.material) ? m.material.map((x) => x.clone()) : m.material.clone();
      list.push({ mesh: m, role: roleOf(names), original: m.material });
    });
    const roles = list.map((e) => e.role);
    return { scene: root, entries: list, levels: lodLevels(roles), hasCollision: roles.some((r) => r.kind === "collision") };
  }, [gltf.scene]);

  useEffect(() => {
    const shown = level !== null && levels.includes(level) ? level : (levels[0] ?? 0);
    const box = new THREE.Box3();
    let triangles = 0;
    for (const { mesh, role, original } of entries) {
      mesh.visible = isVisible(role, shown, showCollision);
      if (role.kind === "collision") {
        mesh.material = COLLISION;
        continue;
      }
      mesh.material = mode === "clay" ? CLAY : original;
      for (const mat of Array.isArray(original) ? original : [original]) (mat as THREE.MeshStandardMaterial).wireframe = mode === "wire";
      if (!mesh.visible) continue;
      const g = mesh.geometry;
      triangles += (g.index ? g.index.count : (g.attributes.position?.count ?? 0)) / 3;
      box.expandByObject(mesh);
    }
    const size = box.isEmpty() ? new THREE.Vector3() : box.getSize(new THREE.Vector3());
    onInfo({ levels, hasCollision, triangles: Math.round(triangles), size: [size.x, size.y, size.z] });
  }, [entries, levels, hasCollision, mode, level, showCollision, onInfo]);

  return <primitive object={scene} />;
}

function Lighting({ light }: { light: Light }) {
  const { gl, scene } = useThree();
  useEffect(() => {
    // image-based lighting from a procedural room: no network, no HDR files
    const pmrem = new THREE.PMREMGenerator(gl);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    return () => {
      scene.environment = null;
      env.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);
  useEffect(() => {
    scene.environmentIntensity = light === "outdoor" ? 0.45 : light === "soft" ? 1.25 : 0.85;
  }, [light, scene]);
  if (light === "outdoor") return <directionalLight position={[6, 9, 4]} intensity={3.2} color="#fff4e0" />;
  if (light === "soft") return <ambientLight intensity={0.35} />;
  return (
    <>
      <directionalLight position={[4, 6, 5]} intensity={1.6} />
      <directionalLight position={[-5, 3, -4]} intensity={0.6} />
    </>
  );
}

/** Hands the parent two commands that need the renderer: re-frame the model, and take a PNG of the current view. */
function Bridge({ reset, capture }: { reset: MutableRefObject<() => void>; capture: MutableRefObject<() => string | null> }) {
  const bounds = useBounds();
  const { gl, scene, camera } = useThree();
  useEffect(() => {
    reset.current = () => {
      bounds.refresh().clip().fit();
    };
    capture.current = () => {
      gl.render(scene, camera);
      return gl.domElement.toDataURL("image/png");
    };
  }, [bounds, gl, scene, camera, reset, capture]);
  return null;
}

class Catch extends Component<{ children: ReactNode; onError: () => void }, { bad: boolean }> {
  state = { bad: false };
  static getDerivedStateFromError() {
    return { bad: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.bad ? null : this.props.children;
  }
}

export default function Viewer({ url, name, testOutput }: { url: string | null; name?: string; testOutput?: boolean }) {
  const [mode, setMode] = useState<Mode>("textured");
  const [light, setLight] = useState<Light>("studio");
  const [level, setLevel] = useState<number | null>(null);
  const [collision, setCollision] = useState(false);
  const [spin, setSpin] = useState(false);
  const [info, setInfo] = useState<Info | null>(null);
  const [failed, setFailed] = useState(false);
  const reset = useRef<() => void>(() => undefined);
  const capture = useRef<() => string | null>(() => null);

  useEffect(() => {
    setFailed(false);
    setInfo(null);
    setLevel(null);
    setCollision(false);
  }, [url]);

  function screenshot() {
    const data = capture.current();
    if (!data) return;
    const a = document.createElement("a");
    a.href = data;
    a.download = `${(name ?? "model").replace(/[^A-Za-z0-9._-]+/g, "_")}.png`;
    a.click();
  }

  if (!url || failed) {
    return (
      <div className="viewer">
        <div className="viewer-empty">
          <div className="viewer-empty-mark" aria-hidden="true" />
          <p>{failed ? "This model could not be loaded. Open it again from your models." : "Your 3D model appears here."}</p>
          {!failed && <p className="muted">Upload an image on the left and press Generate.</p>}
        </div>
      </div>
    );
  }

  const size = info ? formatSize(info.size) : null;
  const shown = info && level !== null && info.levels.includes(level) ? level : (info?.levels[0] ?? 0);
  return (
    <div className="viewer" data-loaded={info ? "true" : "false"}>
      <div className="viewer-bar top">
        <div className="seg" role="group" aria-label="Render mode">
          {(["textured", "clay", "wire"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}>
              {m === "textured" ? "Textured" : m === "clay" ? "Clay" : "Wireframe"}
            </button>
          ))}
        </div>
        <div className="viewer-tools">
          {info && info.levels.length > 1 && (
            <label className="inline">
              <span>Detail</span>
              <select aria-label="Level of detail" value={shown} onChange={(e) => setLevel(Number(e.target.value))}>
                {info.levels.map((l) => (
                  <option key={l} value={l}>
                    LOD{l}
                  </option>
                ))}
              </select>
            </label>
          )}
          {info?.hasCollision && (
            <button type="button" aria-pressed={collision} onClick={() => setCollision(!collision)}>
              Collision
            </button>
          )}
          <label className="inline">
            <span>Light</span>
            <select aria-label="Lighting" value={light} onChange={(e) => setLight(e.target.value as Light)}>
              <option value="studio">Studio</option>
              <option value="outdoor">Outdoor</option>
              <option value="soft">Soft</option>
            </select>
          </label>
          <button type="button" aria-pressed={spin} onClick={() => setSpin(!spin)}>
            Turntable
          </button>
          <button type="button" onClick={() => reset.current()}>
            Reset view
          </button>
          <button type="button" onClick={screenshot}>
            Screenshot
          </button>
        </div>
      </div>

      <Catch onError={() => setFailed(true)}>
        <Canvas camera={{ fov: 32, position: [4, 2.6, 5] }} dpr={[1, 2]} gl={{ preserveDrawingBuffer: true, antialias: true }}>
          <Lighting light={light} />
          <Suspense fallback={null}>
            <Bounds fit clip observe margin={1.25}>
              <Model url={url} mode={mode} level={level} showCollision={collision} onInfo={setInfo} />
              <Bridge reset={reset} capture={capture} />
            </Bounds>
            <ContactShadows position={[0, -0.002, 0]} opacity={0.45} scale={40} blur={2.4} far={12} resolution={512} />
          </Suspense>
          <Grid infiniteGrid fadeDistance={40} fadeStrength={2} cellSize={1} sectionSize={5} cellColor="#39404f" sectionColor="#566076" position={[0, -0.004, 0]} />
          <OrbitControls makeDefault autoRotate={spin} autoRotateSpeed={1.4} enableDamping maxPolarAngle={Math.PI * 0.95} />
        </Canvas>
      </Catch>

      {!info && <div className="viewer-loading">Loading model…</div>}
      <div className="viewer-bar bottom">
        {info && (
          <span className="chip" data-testid="viewer-stats">
            {info.triangles.toLocaleString()} triangles{size ? ` · ${size}` : ""}
          </span>
        )}
        {testOutput && (
          <span className="chip warn" data-testid="test-output">
            Test output · not AI
          </span>
        )}
      </div>
    </div>
  );
}
