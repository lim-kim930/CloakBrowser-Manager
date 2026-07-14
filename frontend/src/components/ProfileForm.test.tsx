import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileForm } from "./ProfileForm";
import type { Kernel } from "../lib/api";

const kernels: Kernel[] = [
  { id: "k1", version: "1.0.0.0", source: "downloaded", source_path: null,
    is_default: true, valid: true, profile_count: 0, created_at: "2026-01-01" },
  { id: "k2", version: "2.0.0.0", source: "imported", source_path: "D:\\k2",
    is_default: false, valid: true, profile_count: 0, created_at: "2026-01-02" },
];

describe("ProfileForm kernel selection", () => {
  it("defaults to follow-default and lists kernels", () => {
    render(<ProfileForm profile={null} kernels={kernels} onSave={vi.fn()} onCancel={vi.fn()} />);
    const select = screen.getByLabelText(/kernel/i) as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByText(/follow default \(1\.0\.0\.0\)/i)).toBeInTheDocument();
    expect(screen.getByText("2.0.0.0")).toBeInTheDocument();
  });

  it("submits selected kernel_id", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} kernels={kernels} onSave={onSave} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/profile name/i), { target: { value: "P" } });
    fireEvent.change(screen.getByLabelText(/kernel/i), { target: { value: "k2" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));
    await vi.waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ kernel_id: "k2" })),
    );
  });
});
