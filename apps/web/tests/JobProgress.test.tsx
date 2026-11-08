import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import JobProgress from "@/components/JobProgress";
import type { Job } from "@/lib/api";

const base: Job = {
  job_id: "j1", name: "Pickup truck", engine: "triposg", state: "generating", progress: 0.2, status_message: "Generating your 3D model", error: null, attempt: 1,
  cancel_requested: false, credits: { reserved: 10, captured: 0 }, created_at: new Date().toISOString(), started_at: null, finished_at: null, result: null,
};

describe("JobProgress", () => {
  it("shows the live stage and a cancel button", () => {
    render(<JobProgress job={base} error={null} onCancel={vi.fn()} />);
    expect(screen.getByText("Generating your 3D model")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
  it("cannot be cancelled while the model is being saved", () => {
    render(<JobProgress job={{ ...base, state: "uploading" }} error={null} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
  it("explains a failure and says the credits came back", () => {
    render(<JobProgress job={{ ...base, state: "failed", error: { code: "model_error", message: "The model could not produce a valid result from this image." } }} error={null} onCancel={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("did not finish");
    expect(screen.getByRole("alert")).toHaveTextContent("The model could not produce a valid result");
    expect(screen.getByRole("alert")).toHaveTextContent("credits were returned");
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });
  it("tells the user when the server cannot be reached but keeps trying", () => {
    render(<JobProgress job={base} error={{ message: "The server could not be reached." } as never} onCancel={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Still trying");
  });
});
