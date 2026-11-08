import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import UploadPanel, { checkFile } from "@/components/UploadPanel";

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

const file = (name: string, type: string, size = 100) => new File([new Uint8Array(size)], name, { type });

describe("UploadPanel", () => {
  it("accepts PNG, JPEG and WebP within the size limit", () => {
    for (const t of ["image/png", "image/jpeg", "image/webp"]) expect(checkFile(file("a", t), 10)).toBeNull();
  });
  it("rejects other types and oversized files with a plain message", () => {
    expect(checkFile(file("a.gif", "image/gif"), 10)).toMatch(/PNG, JPG or WebP/);
    expect(checkFile(file("big.png", "image/png", 11_000_000), 10)).toMatch(/limit is 10 MB/);
  });
  it("passes an accepted file up and shows a preview", () => {
    const onFile = vi.fn();
    render(<UploadPanel maxMb={10} onFile={onFile} />);
    fireEvent.change(screen.getByLabelText("Image file"), { target: { files: [file("car.png", "image/png")] } });
    expect(onFile).toHaveBeenLastCalledWith(expect.objectContaining({ name: "car.png" }));
    expect(screen.getByAltText("Preview of car.png")).toBeInTheDocument();
  });
  it("does not pass a rejected file up", () => {
    const onFile = vi.fn();
    render(<UploadPanel maxMb={10} onFile={onFile} />);
    fireEvent.change(screen.getByLabelText("Image file"), { target: { files: [file("x.gif", "image/gif")] } });
    expect(onFile).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole("alert")).toHaveTextContent("PNG, JPG or WebP");
  });
});
