import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Activity from "@/components/Activity";
import AssetPanel from "@/components/AssetPanel";
import CreatePanel from "@/components/CreatePanel";
import { ApiError, type Api, type AssetDetail, type Job, type Me } from "@/lib/api";

const me = (over: Partial<Me> = {}): Me => ({
  user_id: "u", email: "a@b.c", new_user: false, credits: { balance: 100, reserved: 0 }, price: { image_to_3d: 10 }, engines: ["triposg"],
  limits: { max_upload_mb: 10, min_image_side: 256, max_active_jobs: 2, target_faces: [2000, 25000], export_formats: ["obj", "stl", "ply"] }, ...over,
});

const detail = (over: Partial<AssetDetail> = {}): AssetDetail => ({
  asset_id: "a1", name: "Red car", category: "car", created_at: "2026-11-11T10:00:00Z", current_version: 1, triangles: 1920, has_uv: true, engine: "triposg", ai_inference: true,
  metadata: { upload_id: "up1", job_id: "j1" },
  model: {
    version: 1, triangles: 1920, vertices: 1432, extents_m: [2.46, 1.24, 4.5], lods: [{ level: 0, triangles: 1920 }, { level: 1, triangles: 959 }], collision_triangles: 252,
    has_uv: true, bytes: 135024, engine: "triposg", engine_version: "x", ai_inference: true, test_double: false, settings: { preset: "STANDARD", category: "car", target_faces: 24000, texture_resolution: 1024 },
    files: [{ role: "glb", bytes: 135024 }, { role: "raw_mesh", bytes: 9000 }, { role: "thumbnail", bytes: 100 }],
    checks: {
      status: "NEEDS_REVIEW", overall: 78.7, critical_failures: 3, major_failures: 6, blocking_reasons: ["3 critical failure(s)"],
      categories: [{ id: "geometry", score: 98.4, failed: 0, warnings: 1, applicable: true }, { id: "vehicle", score: 0, failed: 10, warnings: 0, applicable: true }],
      problems: [{ id: "V001", category: "vehicle", title: "Wheels are separate objects", severity: "critical", status: "failed", message: "no wheel objects found" }],
    },
    needs_human: [], warnings: [],
  },
  ...over,
});

const fakeApi = (over: Partial<Record<keyof Api, unknown>> = {}) =>
  ({ uploadLink: vi.fn(async () => ({ url: "https://store.test/ref.png", content_type: "image/png", width: 512, height: 512 })), ...over }) as unknown as Api;

const noop = () => undefined;
const panel = (api: Api, d = detail(), extra: Partial<Parameters<typeof AssetPanel>[0]> = {}) =>
  render(<AssetPanel api={api} detail={d} price={10} canGenerate formats={["obj", "stl", "ply"]} onRenamed={noop} onDeleted={noop} onVariation={noop} {...extra} />);

describe("AssetPanel", () => {
  it("shows the facts a person asks about, in plain units", async () => {
    panel(fakeApi());
    expect(screen.getByLabelText("Model name")).toHaveValue("Red car");
    expect(screen.getByText("1,920")).toBeInTheDocument();
    expect(screen.getByText("2.46 × 1.24 × 4.50 m")).toBeInTheDocument();
    expect(screen.getByText("TripoSG")).toBeInTheDocument();
    expect(await screen.findByAltText("The image this model was made from")).toHaveAttribute("src", "https://store.test/ref.png");
  });

  it("labels a model that was not made by AI", () => {
    const d = detail();
    panel(fakeApi(), { ...d, model: { ...d.model!, engine: "other", ai_inference: false, test_double: true } });
    expect(screen.getByText("not AI")).toBeInTheDocument();
  });

  it("renames on Enter and reports the new detail", async () => {
    const renamed = detail({ name: "Blue car" });
    const renameAsset = vi.fn(async () => renamed);
    const onRenamed = vi.fn();
    panel(fakeApi({ renameAsset }), detail(), { onRenamed });
    const input = screen.getByLabelText("Model name");
    fireEvent.change(input, { target: { value: "  Blue car " } });
    fireEvent.blur(input);
    await waitFor(() => expect(onRenamed).toHaveBeenCalledWith(renamed));
    expect(renameAsset).toHaveBeenCalledWith("a1", "Blue car");
  });

  it("does not call the server for an unchanged or empty name", () => {
    const renameAsset = vi.fn();
    panel(fakeApi({ renameAsset }));
    const input = screen.getByLabelText("Model name");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.blur(input);
    expect(renameAsset).not.toHaveBeenCalled();
    expect(input).toHaveValue("Red car");
  });

  it("deletes only after a second, explicit confirmation", async () => {
    const deleteAsset = vi.fn(async () => undefined);
    const onDeleted = vi.fn();
    panel(fakeApi({ deleteAsset }), detail(), { onDeleted });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteAsset).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByRole("button", { name: "Delete this model" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete this model" }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("a1"));
  });

  it("shows the price of a variation and blocks it when a generation cannot start", () => {
    const onVariation = vi.fn();
    const { unmount } = panel(fakeApi(), detail(), { onVariation });
    fireEvent.click(screen.getByRole("button", { name: /Make a variation · 10 credits/ }));
    expect(onVariation).toHaveBeenCalledTimes(1);
    unmount();
    panel(fakeApi(), detail(), { canGenerate: false });
    expect(screen.getByRole("button", { name: /Make a variation/ })).toBeDisabled();
  });

  it("summarises the game-readiness checks and reveals the issues on request", () => {
    panel(fakeApi());
    fireEvent.click(screen.getByRole("tab", { name: "Game-ready checks" }));
    expect(screen.getByText("79%")).toBeInTheDocument();
    expect(screen.getByText(/Needs review/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Vehicle setup: 0 percent" })).toBeInTheDocument();
    expect(screen.getByText(/LOD0 1,920 · LOD1 959 triangles · collision mesh 252/)).toBeInTheDocument();
    expect(screen.queryByText("Wheels are separate objects")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show 1 issue" }));
    expect(screen.getByText("Wheels are separate objects")).toBeInTheDocument();
  });

  it("offers only the downloads that exist and reports a failed one", async () => {
    const exportUrl = vi.fn(async () => { throw new ApiError(503, "storage_unavailable", "The file store is not reachable right now.", "Try again in a moment."); });
    panel(fakeApi({ exportUrl }), detail(), { formats: ["obj"] });
    fireEvent.click(screen.getByRole("tab", { name: "Download" }));
    expect(screen.getByText("GLB")).toBeInTheDocument();
    expect(screen.getByText("OBJ")).toBeInTheDocument();
    expect(screen.getByText("Raw GLB")).toBeInTheDocument();
    expect(screen.queryByText("STL")).toBeNull();
    expect(screen.getByText(/FBX, USDZ and .blend are not available yet/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Download" })[1]!);
    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable right now. Try again in a moment.");
    expect(exportUrl).toHaveBeenCalledWith("a1", 1, "obj");
  });
});

describe("CreatePanel", () => {
  const file = new File([new Uint8Array(10)], "truck.png", { type: "image/png" });
  const choose = () => fireEvent.change(screen.getByLabelText("Image file"), { target: { files: [file] } });
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();

  it("sends the enabled engine and the chosen settings", () => {
    const onGenerate = vi.fn();
    render(<CreatePanel me={me()} busy={false} blocked={null} problem={null} onGenerate={onGenerate} />);
    expect(screen.getByRole("button", { name: /Generate · 10 credits/ })).toBeDisabled();
    choose();
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "bus" } });
    fireEvent.change(screen.getByLabelText(/Real length/), { target: { value: "11.5" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate · 10 credits/ }));
    expect(onGenerate).toHaveBeenCalledWith(expect.objectContaining({ engine: "triposg", name: "truck", category: "bus", preset: "STANDARD", faces: 24000, texture: 1024, lengthM: 11.5 }));
  });

  it("explains why nothing can be generated when no model is enabled", () => {
    render(<CreatePanel me={me({ engines: [] })} busy={false} blocked={null} problem={null} onGenerate={vi.fn()} />);
    choose();
    expect(screen.getByRole("status")).toHaveTextContent("No AI model is switched on");
    expect(screen.getByRole("button", { name: /Generate/ })).toBeDisabled();
  });

  it("blocks on too few credits, a bad length, or a full queue", () => {
    const { rerender } = render(<CreatePanel me={me({ credits: { balance: 3, reserved: 0 } })} busy={false} blocked={null} problem={null} onGenerate={vi.fn()} />);
    choose();
    expect(screen.getByText(/You need 10 credits to generate and have 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate/ })).toBeDisabled();
    rerender(<CreatePanel me={me()} busy={false} blocked={null} problem={null} onGenerate={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Real length/), { target: { value: "500" } });
    expect(screen.getByText("Enter a length between 0 and 60 metres.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Real length/), { target: { value: "" } });
    rerender(<CreatePanel me={me()} busy={false} blocked="You already have 2 generations running." problem={null} onGenerate={vi.fn()} />);
    expect(screen.getByText("You already have 2 generations running.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate/ })).toBeDisabled();
  });

  it("keeps the triangle budget inside what the pipeline accepts", () => {
    const onGenerate = vi.fn();
    render(<CreatePanel me={me()} busy={false} blocked={null} problem={null} onGenerate={onGenerate} />);
    choose();
    fireEvent.click(screen.getByRole("button", { name: "Show advanced settings" }));
    fireEvent.change(screen.getByLabelText("Triangle budget"), { target: { value: "999999" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(onGenerate).toHaveBeenCalledWith(expect.objectContaining({ faces: 25000 }));
  });
});

describe("Activity", () => {
  const job = (over: Partial<Job>): Job => ({
    job_id: "j1", name: "Car", engine: "triposg", state: "completed", progress: 1, status_message: null, error: null, attempt: 1, cancel_requested: false,
    credits: { reserved: 10, captured: 10 }, created_at: "2026-11-11T10:00:00Z", started_at: null, finished_at: null, result: { asset_id: "a1", version_id: "v1" }, ...over,
  });

  it("says what each generation cost, and that failures were not charged", () => {
    const onOpen = vi.fn();
    render(
      <Activity
        activeId={null}
        onOpen={onOpen}
        jobs={[
          job({}),
          job({ job_id: "j2", name: "Bus", state: "failed", result: null, credits: { reserved: 10, captured: 0 }, error: { code: "model_error", message: "The model could not produce a valid result from this image." } }),
          job({ job_id: "j3", name: "Truck", state: "generating", result: null, credits: { reserved: 10, captured: 0 } }),
        ]}
      />,
    );
    expect(screen.getByText(/10 credits$/)).toBeInTheDocument();
    expect(screen.getByText(/not charged/)).toBeInTheDocument();
    expect(screen.getByText(/10 credits held/)).toBeInTheDocument();
    expect(screen.getByText("The model could not produce a valid result from this image.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Bus/ })).toBeDisabled(); // nothing to open for a failed job
    fireEvent.click(screen.getByRole("button", { name: /Truck/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Car/ }));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("explains itself when empty", () => {
    render(<Activity jobs={[]} activeId={null} onOpen={vi.fn()} />);
    expect(screen.getByText(/Every generation you start is listed here/)).toBeInTheDocument();
  });
});
