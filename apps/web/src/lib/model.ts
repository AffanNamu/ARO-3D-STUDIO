/** Names the pipeline gives the meshes inside a GLB: `*_LOD0..n` are the visual model at falling detail, `COL_*` are collision meshes. */
const LOD = /_LOD(\d+)$/i;
const COLLISION = /^COL_/i;

export type MeshRole = { kind: "collision" } | { kind: "lod"; level: number } | { kind: "plain" };

/** Classify a mesh from its own name and its ancestors' names (loaders may put the name on a parent node). */
export function roleOf(names: readonly string[]): MeshRole {
  for (const n of names) if (COLLISION.test(n)) return { kind: "collision" };
  for (const n of names) {
    const m = LOD.exec(n);
    if (m?.[1] !== undefined) return { kind: "lod", level: Number(m[1]) };
  }
  return { kind: "plain" };
}

/** Which meshes to draw: plain meshes always, LOD meshes only at the chosen level, collision meshes only when asked. */
export function isVisible(role: MeshRole, level: number, showCollision: boolean): boolean {
  if (role.kind === "collision") return showCollision;
  if (role.kind === "lod") return role.level === level;
  return true;
}

export function lodLevels(roles: readonly MeshRole[]): number[] {
  const set = new Set<number>();
  for (const r of roles) if (r.kind === "lod") set.add(r.level);
  return [...set].sort((a, b) => a - b);
}

export const ENGINE_LABELS: Record<string, string> = {
  triposg: "TripoSG",
  fake: "Test double (not AI)",
};

export function engineLabel(id: string | null | undefined): string {
  if (!id) return "Unknown";
  return ENGINE_LABELS[id] ?? id;
}

export const CATEGORIES: ReadonlyArray<readonly [string, string]> = [
  ["car", "Car"],
  ["suv", "SUV"],
  ["pickup", "Pickup"],
  ["bus", "Bus"],
  ["light_truck", "Light truck"],
  ["medium_truck", "Medium truck"],
  ["heavy_truck", "Heavy truck"],
  ["special_vehicle", "Special vehicle"],
  ["building", "Building"],
  ["sign", "Sign"],
  ["street_furniture", "Street furniture"],
  ["prop", "Prop"],
  ["furniture", "Furniture"],
  ["household_object", "Household object"],
  ["equipment", "Equipment & tools"],
  ["other", "Other"],
];

export function categoryLabel(id: string): string {
  return CATEGORIES.find(([v]) => v === id)?.[1] ?? id;
}

/** "4.50 × 1.60 × 4.02 m" from extents in metres (glTF: x = width, y = height, z = length). */
export function formatSize(extents: readonly number[] | null | undefined): string | null {
  if (!extents || extents.length !== 3) return null;
  const f = (n: number) => (n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2));
  const [x, y, z] = extents as [number, number, number];
  return `${f(x)} × ${f(y)} × ${f(z)} m`;
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const CHECK_LABELS: Record<string, string> = {
  geometry: "Geometry",
  materials: "Materials",
  textures: "Textures",
  lod: "Levels of detail",
  collision: "Collision",
  vehicle: "Vehicle setup",
  unity: "Unity import",
};

/** A new seed for a variation: any 31-bit integer the engine accepts. */
export function randomSeed(random: () => number = Math.random): number {
  return Math.floor(random() * 2147483647);
}
