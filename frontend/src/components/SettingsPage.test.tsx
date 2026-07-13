import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import type { Kernel } from "../lib/api";

vi.mock("../lib/pickFolder", () => ({ pickFolder: vi.fn() }));

const kernel: Kernel = {
  id: "k1", version: "1.0.0.0", source: "imported",
  source_path: "D:\\kernels\\chromium-1.0.0.0", is_default: true,
  valid: true, profile_count: 2, created_at: "2026-01-01",
};

function makeLib(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    kernels: [kernel], loading: false, error: null,
    downloadState: { state: "idle" as const, error: null },
    refresh: vi.fn(), importKernel: vi.fn(), startDownload: vi.fn(),
    setDefault: vi.fn(), remove: vi.fn(),
    ...overrides,
  };
}

describe("SettingsPage", () => {
  it("renders kernel rows with version, source, path, default badge", () => {
    render(<SettingsPage kernelLib={makeLib()} />);
    expect(screen.getByText("1.0.0.0")).toBeInTheDocument();
    expect(screen.getByText(/D:\\kernels/)).toBeInTheDocument();
    expect(screen.getByText(/default/i)).toBeInTheDocument();
    expect(screen.getByText(/2 profile/i)).toBeInTheDocument();
  });

  it("flags invalid kernels", () => {
    const lib = makeLib({ kernels: [{ ...kernel, valid: false }] });
    render(<SettingsPage kernelLib={lib} />);
    expect(screen.getByText(/missing/i)).toBeInTheDocument();
  });

  it("import button picks a folder then calls importKernel", async () => {
    const { pickFolder } = await import("../lib/pickFolder");
    vi.mocked(pickFolder).mockResolvedValue("D:\\new-kernel");
    const lib = makeLib();
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /import/i }));
    await vi.waitFor(() => expect(lib.importKernel).toHaveBeenCalledWith("D:\\new-kernel"));
  });

  it("download button triggers startDownload", () => {
    const lib = makeLib();
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /download/i }));
    expect(lib.startDownload).toHaveBeenCalled();
  });

  it("shows progress while downloading", () => {
    const lib = makeLib({ downloadState: { state: "downloading", error: null } });
    render(<SettingsPage kernelLib={lib} />);
    expect(screen.getByText(/Downloading browser kernel/i)).toBeInTheDocument();
  });

  it("delete asks for confirmation", () => {
    const lib = makeLib();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    expect(lib.remove).toHaveBeenCalledWith("k1");
  });
});
