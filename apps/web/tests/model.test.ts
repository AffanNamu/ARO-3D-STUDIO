import { describe, expect, it } from "vitest";
import { categoryLabel, engineLabel, formatBytes, formatSize, isVisible, lodLevels, randomSeed, roleOf } from "@/lib/model";

describe("mesh roles inside a pipeline GLB", () => {
  it("recognises detail levels and collision meshes from a mesh's own name or an ancestor's", () => {
    expect(roleOf(["Car_LOD0"])).toEqual({ kind: "lod", level: 0 });
    expect(roleOf(["mesh_0", "Raw_Mesh_LOD3", ""])).toEqual({ kind: "lod", level: 3 });
    expect(roleOf(["COL_Hull"])).toEqual({ kind: "collision" });
    expect(roleOf(["Mesh", "col_box_01"])).toEqual({ kind: "collision" });
    expect(roleOf(["Body", "Scene"])).toEqual({ kind: "plain" });
    expect(roleOf(["LOD0_not_a_suffix"])).toEqual({ kind: "plain" });
  });
  it("draws one detail level at a time, never the collision mesh unless asked", () => {
    const lod0 = roleOf(["A_LOD0"]), lod2 = roleOf(["A_LOD2"]), col = roleOf(["COL_A"]), plain = roleOf(["A"]);
    expect([lod0, lod2, col, plain].map((r) => isVisible(r, 0, false))).toEqual([true, false, false, true]);
    expect([lod0, lod2, col, plain].map((r) => isVisible(r, 2, true))).toEqual([false, true, true, true]);
  });
  it("lists the levels present, in order, once each", () => {
    expect(lodLevels([roleOf(["x_LOD2"]), roleOf(["x_LOD0"]), roleOf(["y_LOD2"]), roleOf(["COL_x"]), roleOf(["z"])])).toEqual([0, 2]);
    expect(lodLevels([roleOf(["plain"])])).toEqual([]);
  });
});

describe("labels and formatting", () => {
  it("names engines honestly", () => {
    expect(engineLabel("triposg")).toBe("TripoSG");
    expect(engineLabel("fake")).toBe("Test double (not AI)");
    expect(engineLabel("something-new")).toBe("something-new");
    expect(engineLabel(null)).toBe("Unknown");
  });
  it("formats sizes in metres and file sizes", () => {
    expect(formatSize([2.4616, 1.244, 4.5])).toBe("2.46 × 1.24 × 4.50 m");
    expect(formatSize([12.34, 3, 120.4])).toBe("12.3 × 3.00 × 120 m");
    expect(formatSize(null)).toBeNull();
    expect(formatSize([1, 2])).toBeNull();
    expect(formatBytes(900)).toBe("900 B");
    expect(formatBytes(135024)).toBe("132 KB");
    expect(formatBytes(5_500_000)).toBe("5.2 MB");
    expect(formatBytes(null)).toBe("—");
  });
  it("labels categories and falls back to the id", () => {
    expect(categoryLabel("heavy_truck")).toBe("Heavy truck");
    expect(categoryLabel("unknown_thing")).toBe("unknown_thing");
  });
  it("makes seeds the engine accepts", () => {
    expect(randomSeed(() => 0)).toBe(0);
    expect(randomSeed(() => 0.999999999)).toBeLessThanOrEqual(2147483647);
    expect(Number.isInteger(randomSeed())).toBe(true);
  });
});
