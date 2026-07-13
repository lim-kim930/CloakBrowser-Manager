import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { useKernels } from "./useKernels";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    listKernels: vi.fn(),
    importKernel: vi.fn(),
    downloadKernel: vi.fn(),
    downloadStatus: vi.fn(),
    setDefaultKernel: vi.fn(),
    deleteKernel: vi.fn(),
  },
}));

const kernel = {
  id: "k1", version: "1.0.0.0", source: "downloaded" as const, source_path: null,
  is_default: true, valid: true, profile_count: 0, created_at: "2026-01-01",
};

beforeEach(() => {
  // Config sets no global clearMocks, so reset call history between tests
  // (the importKernel refresh test asserts an exact call count).
  vi.clearAllMocks();
  vi.mocked(api.listKernels).mockResolvedValue([kernel]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useKernels", () => {
  it("loads kernels on mount", async () => {
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.kernels).toEqual([kernel]);
  });

  it("importKernel calls api and refreshes", async () => {
    vi.mocked(api.importKernel).mockResolvedValue(kernel);
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.importKernel("D:\\k"));
    expect(api.importKernel).toHaveBeenCalledWith("D:\\k");
    expect(api.listKernels).toHaveBeenCalledTimes(2);
  });

  it("importKernel surfaces API error message", async () => {
    vi.mocked(api.importKernel).mockRejectedValue(new Error("Not a directory: D:\\k"));
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.importKernel("D:\\k"));
    expect(result.current.error).toContain("Not a directory");
  });

  it("startDownload polls status until ready then refreshes", async () => {
    vi.useFakeTimers();
    vi.mocked(api.downloadKernel).mockResolvedValue({ ok: true });
    vi.mocked(api.downloadStatus)
      .mockResolvedValueOnce({ state: "downloading", error: null })
      .mockResolvedValue({ state: "ready", error: null });
    const { result } = renderHook(() => useKernels());
    await act(async () => { await vi.runOnlyPendingTimersAsync(); });
    await act(() => result.current.startDownload());
    expect(result.current.downloadState.state).toBe("downloading");
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(result.current.downloadState.state).toBe("ready");
    vi.useRealTimers();
  });
});
