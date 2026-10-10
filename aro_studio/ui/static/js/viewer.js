// Interactive 3D viewer (three.js, vendored). Asset convention: metres, +Y up, +Z forward, +X = vehicle left.
import * as THREE from '../vendor/three-viewer.min.js';

const LOD_RE = /_LOD(\d+)$/;

export class Viewer {
  constructor(container) {
    this.container = container;
    this.ok = true;
    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch (e) { this.ok = false; this.error = e; return; }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NeutralToneMapping; // Khronos PBR Neutral: keeps base colours faithful
    this.renderer.toneMappingExposure = 1.0;
    this.canvas = this.renderer.domElement; this.canvas.className = 'viewer'; this.canvas.tabIndex = 0;
    this.canvas.setAttribute('aria-label', '3D viewport: drag to orbit, right-drag to pan, scroll to zoom');
    container.append(this.canvas);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.05, 500);
    this.controls = new THREE.OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = false; this.controls.screenSpacePanning = true;
    this.controls.addEventListener('change', () => this.requestRender());
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.env = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture; pmrem.dispose();
    this.scene.environment = this.env; this.scene.environmentIntensity = 0.7;
    this.key = new THREE.DirectionalLight(0xffffff, 1.4); this.scene.add(this.key, this.key.target);
    this.fill = new THREE.HemisphereLight(0xbfd4ff, 0x20242a, 0.25); this.scene.add(this.fill);
    this.light = { key: 1.4, env: 0.7, azimuth: 35, exposure: 1.0 };
    this.root = null; this.lodNodes = new Map(); this.collisionGroup = null;
    this.overlays = new THREE.Group(); this.scene.add(this.overlays);
    this.gridObj = null; this.bboxObj = null; this.colHelpers = null; this.rigHelpers = null;
    this.flags = { wire: false, grid: true, bbox: false, collision: false, rig: false, shading: 'pbr' };
    this.lod = 0; this.fileSize = 0; this.radius = 5; this.center = new THREE.Vector3();
    this.origMaterials = new Map(); this.dirty = true;
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(container);
    this.resize(); this.loop();
  }

  resize() {
    if (!this.ok) return;
    const w = Math.max(10, this.container.clientWidth), h = Math.max(10, this.container.clientHeight);
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.requestRender();
  }
  requestRender() { this.dirty = true; }
  loop() {
    if (!this.ok || this.disposed) return;
    if (this.dirty) { this.dirty = false; this.updateLight(); this.renderer.render(this.scene, this.camera); }
    this.raf = requestAnimationFrame(() => this.loop());
  }
  updateLight() {
    const a = THREE.MathUtils.degToRad(this.light.azimuth), r = Math.max(this.radius, 1) * 2;
    this.key.position.set(this.center.x + Math.sin(a) * r, this.center.y + r, this.center.z + Math.cos(a) * r);
    this.key.target.position.copy(this.center); this.key.intensity = this.light.key;
    this.scene.environmentIntensity = this.light.env; this.renderer.toneMappingExposure = this.light.exposure;
  }

  async load(arrayBuffer) {
    this.clearModel(); this.fileSize = arrayBuffer.byteLength;
    const gltf = await new Promise((res, rej) => new THREE.GLTFLoader().parse(arrayBuffer, '', res, rej));
    this.root = gltf.scene; this.scene.add(this.root);
    this.lodNodes.clear(); this.origMaterials.clear(); this.collisionGroup = null;
    this.root.traverse((o) => {
      if (o.name === 'Collision') this.collisionGroup = o;
      const m = LOD_RE.exec(o.name || '');
      if (m && o.isMesh && !this.insideCollision(o)) { const n = Number(m[1]); if (!this.lodNodes.has(n)) this.lodNodes.set(n, []); this.lodNodes.get(n).push(o); }
      if (o.isMesh) { o.frustumCulled = true; this.origMaterials.set(o, o.material); }
    });
    this.meta = (this.root.userData && this.root.userData.aro_studio) || (this.root.children[0]?.userData?.aro_studio) || null;
    if (!this.meta) this.root.traverse((o) => { if (!this.meta && o.userData?.aro_studio) this.meta = o.userData.aro_studio; });
    this.lod = 0; this.applyLod(); this.applyCollision(); this.applyShading(); this.applyWire(); this.frame(); this.buildOverlays();
    return this.stats();
  }
  insideCollision(o) { for (let p = o; p; p = p.parent) if (p.name === 'Collision') return true; return false; }
  get lodLevels() { return [...this.lodNodes.keys()].sort((a, b) => a - b); }

  clearModel() {
    if (this.root) { this.scene.remove(this.root); this.root.traverse((o) => { o.geometry?.dispose?.(); }); this.root = null; }
    this.overlays.clear(); this.gridObj = this.bboxObj = this.colHelpers = this.rigHelpers = null;
  }

  visibleVisuals() {
    const out = []; if (!this.root) return out;
    this.root.traverse((o) => { if (o.isMesh && !this.insideCollision(o) && this.effectiveVisible(o)) out.push(o); });
    return out;
  }
  effectiveVisible(o) { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; }

  bounds() { const b = new THREE.Box3(); for (const m of this.visibleVisuals()) b.expandByObject(m); return b; }
  frame() {
    this.root?.updateMatrixWorld(true);
    const b = this.bounds(); if (b.isEmpty()) return;
    const sph = b.getBoundingSphere(new THREE.Sphere()); this.radius = sph.radius; this.center.copy(sph.center);
    this.camera.near = Math.max(0.01, sph.radius / 200); this.camera.far = sph.radius * 60; this.camera.updateProjectionMatrix();
    this.controls.target.copy(this.center); this.controls.maxDistance = sph.radius * 20; this.controls.minDistance = sph.radius * 0.05;
    this.setView('iso');
  }
  setView(name) {
    if (!this.ok) return;
    const d = (this.radius / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2))) * 1.05;
    const dirs = { front: [0, 0, 1], rear: [0, 0, -1], left: [1, 0, 0], right: [-1, 0, 0], top: [0, 1, 0.0001], bottom: [0, -1, 0.0001], iso: [0.75, 0.4, 0.85] };
    const v = new THREE.Vector3(...(dirs[name] || dirs.iso)).normalize().multiplyScalar(d);
    this.camera.position.copy(this.center).add(v); this.camera.up.set(0, 1, 0); this.controls.target.copy(this.center); this.controls.update(); this.requestRender();
  }
  reset() { this.frame(); }

  applyLod() {
    if (!this.lodNodes.size) return;
    for (const [lv, nodes] of this.lodNodes) for (const n of nodes) n.visible = lv === this.lod;
    this.requestRender();
  }
  setLod(n) { this.lod = n; this.applyLod(); this.buildOverlays(); }
  applyCollision() {
    if (!this.collisionGroup) return;
    this.collisionGroup.visible = this.flags.collision;
    this.collisionGroup.traverse((o) => { if (o.isMesh) { o.material = this.colMat ||= new THREE.MeshBasicMaterial({ color: 0x3ddc97, wireframe: true, transparent: true, opacity: 0.8, depthTest: false }); o.renderOrder = 10; } });
    this.requestRender();
  }
  applyShading() {
    const mode = this.flags.shading;
    for (const [mesh, orig] of this.origMaterials) {
      if (this.insideCollision(mesh)) continue;
      if (mode === 'pbr') mesh.material = orig;
      else if (mode === 'clay') mesh.material = this.clayMat ||= new THREE.MeshStandardMaterial({ color: 0xb8bec7, roughness: 0.75, metalness: 0.0 });
      else mesh.material = this.normalMat ||= new THREE.MeshNormalMaterial();
    }
    this.applyWire();
  }
  applyWire() {
    const set = new Set();
    this.root?.traverse((o) => { if (o.isMesh && !this.insideCollision(o)) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => set.add(m)); });
    set.forEach((m) => { m.wireframe = this.flags.wire; m.needsUpdate = true; });
    for (const orig of new Set(this.origMaterials.values())) orig.wireframe = this.flags.wire && this.flags.shading === 'pbr';
    this.requestRender();
  }
  set(flag, value) {
    this.flags[flag] = value;
    if (flag === 'wire') this.applyWire(); else if (flag === 'shading') this.applyShading(); else if (flag === 'collision') { this.applyCollision(); this.buildOverlays(); } else this.buildOverlays();
    this.requestRender();
  }
  setLight(patch) { Object.assign(this.light, patch); this.requestRender(); }

  buildOverlays() {
    if (!this.ok) return;
    this.overlays.clear(); if (!this.root) return;
    this.root.updateMatrixWorld(true);
    const size = Math.ceil(this.radius * 4);
    if (this.flags.grid) {
      const g = new THREE.GridHelper(size, size, 0x3a4656, 0x222a34); g.position.set(this.center.x, 0, this.center.z); g.material.transparent = true; g.material.opacity = 0.8; this.overlays.add(g);
      const ax = new THREE.AxesHelper(Math.max(1, this.radius * 0.35)); this.overlays.add(ax);
    }
    if (this.flags.bbox) { const b = this.bounds(); if (!b.isEmpty()) { const h = new THREE.Box3Helper(b, 0xff6a1a); this.overlays.add(h); } }
    if (this.flags.collision && this.collisionGroup) this.addColliderHelpers();
    if (this.flags.rig) this.addRigHelpers();
    this.requestRender();
  }
  addColliderHelpers() {
    const mat = new THREE.LineBasicMaterial({ color: 0x3ddc97, depthTest: false });
    this.collisionGroup.traverse((o) => {
      const c = o.userData?.aro_collider; if (!c || o.isMesh) return;
      const p = o.getWorldPosition(new THREE.Vector3()); let geo = null;
      if (c.kind === 'box' && c.size) geo = new THREE.BoxGeometry(...c.size);
      else if (c.kind === 'sphere' && c.radius) geo = new THREE.SphereGeometry(c.radius, 16, 12);
      else if (c.kind === 'capsule' && c.radius) { geo = new THREE.CapsuleGeometry(c.radius, Math.max(0, (c.height || 2 * c.radius) - 2 * c.radius), 6, 12); if (c.axis === 'X') geo.rotateZ(Math.PI / 2); else if (c.axis === 'Z') geo.rotateX(Math.PI / 2); }
      if (!geo) return;
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 20), mat); e.position.copy(p); e.renderOrder = 11; this.overlays.add(e);
    });
  }
  addRigHelpers() {
    const len = Math.max(0.25, this.radius * 0.12);
    this.root.traverse((o) => {
      const r = o.userData?.aro_rig; if (!r) return;
      const p = o.getWorldPosition(new THREE.Vector3());
      const color = { wheel_spin: 0xff6a1a, steering: 0x5cb8ff, suspension: 0xffc247, door: 0xff5c6c, mirror: 0xff5c6c, wiper: 0xff5c6c, light: 0xffffaa, attachment: 0xc792ff }[r.role] || 0x9aa7b8;
      const axis = r.axis ? new THREE.Vector3(...r.axis).normalize() : new THREE.Vector3(0, 1, 0);
      const a = new THREE.ArrowHelper(axis, p, r.role === 'light' ? len * 0.8 : len, color, len * 0.28, len * 0.16);
      a.line.material.depthTest = false; a.cone.material.depthTest = false; a.renderOrder = 12; this.overlays.add(a);
    });
  }

  stats() {
    const vis = this.visibleVisuals(); let verts = 0, tris = 0; const mats = new Set(), imgs = new Set();
    for (const m of vis) {
      const g = m.geometry; verts += g.attributes.position.count; tris += g.index ? g.index.count / 3 : g.attributes.position.count / 3;
      for (const mt of this.origMaterials.has(m) ? [this.origMaterials.get(m)] : [m.material]) { mats.add(mt.name || mt.uuid); ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap'].forEach((k) => mt[k]?.image && imgs.add(mt[k].image)); }
    }
    const b = this.bounds(); const size = b.isEmpty() ? [0, 0, 0] : b.getSize(new THREE.Vector3()).toArray();
    const lods = this.lodLevels.map((lv) => ({ level: lv, triangles: this.lodNodes.get(lv).reduce((s, m) => s + (m.geometry.index ? m.geometry.index.count / 3 : 0), 0) }));
    return { vertices: verts, triangles: Math.round(tris), materials: mats.size, textures: imgs.size, dimensions: size, fileSize: this.fileSize, lod: this.lod, lods, meta: this.meta };
  }

  screenshot() { this.renderer.render(this.scene, this.camera); return this.canvas.toDataURL('image/png'); }
  dispose() {
    this.disposed = true; cancelAnimationFrame(this.raf); this.ro?.disconnect(); this.clearModel();
    this.env?.dispose?.(); this.renderer?.dispose?.(); this.canvas?.remove();
  }
}
