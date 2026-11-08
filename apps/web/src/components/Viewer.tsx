"use client";
import { Bounds, Center, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Component, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import * as THREE from "three";

function Model({ url, wireframe, onStats }: { url: string; wireframe: boolean; onStats: (tris: number) => void }) {
  const gltf = useGLTF(url);
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);
  useEffect(() => {
    let tris = 0;
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const g = m.geometry;
      tris += (g.index ? g.index.count : (g.attributes.position?.count ?? 0)) / 3;
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      for (const mat of mats) (mat as THREE.MeshStandardMaterial).wireframe = wireframe;
    });
    onStats(Math.round(tris));
  }, [scene, wireframe, onStats]);
  return <Center><primitive object={scene} /></Center>;
}

export default function Viewer({ url, filename }: { url: string | null; filename?: string }) {
  const [wire, setWire] = useState(false);
  const [spin, setSpin] = useState(false);
  const [tris, setTris] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); setTris(null); }, [url]);

  return (
    <div className="viewer">
      {url && !failed && (
        <>
          <div className="tools">
            <button type="button" aria-pressed={wire} onClick={() => setWire(!wire)}>Wireframe</button>
            <button type="button" aria-pressed={spin} onClick={() => setSpin(!spin)}>Turntable</button>
            <a href={url} download={filename ?? "model.glb"}><button type="button">Download GLB</button></a>
            {tris !== null && <span className="pill">{tris.toLocaleString()} triangles</span>}
          </div>
          <ErrorCatcher onError={() => setFailed(true)}>
            <Canvas camera={{ fov: 35, position: [3, 2, 4] }} dpr={[1, 2]}>
              <hemisphereLight intensity={1.1} groundColor="#444" />
              <directionalLight position={[4, 6, 5]} intensity={2.2} />
              <directionalLight position={[-5, 2, -4]} intensity={0.8} />
              <Suspense fallback={null}>
                <Bounds fit clip observe margin={1.25}>
                  <Model url={url} wireframe={wire} onStats={setTris} />
                </Bounds>
              </Suspense>
              <Grid infiniteGrid fadeDistance={30} cellColor="#445" sectionColor="#667" position={[0, -0.001, 0]} />
              <OrbitControls makeDefault autoRotate={spin} autoRotateSpeed={1.5} enableDamping />
            </Canvas>
          </ErrorCatcher>
        </>
      )}
      {(!url || failed) && (
        <div className="empty">{failed ? "The model could not be loaded. Try opening it again from your library." : "Your model appears here. Upload an image and press Generate."}</div>
      )}
    </div>
  );
}

class ErrorCatcher extends Component<{ children: ReactNode; onError: () => void }, { bad: boolean }> {
  state = { bad: false };
  static getDerivedStateFromError() { return { bad: true }; }
  componentDidCatch() { this.props.onError(); }
  render() { return this.state.bad ? null : this.props.children; }
}
