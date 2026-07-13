import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useBootstrap } from "./useBootstrap";
import type { BackendSnapshot } from "./tauri";

vi.mock("./tauri", () => ({
  isTauri: vi.fn(),
  invoke: vi.fn(),
  listen: vi.fn(),
}));
vi.mock("../lib/api", () => ({
  api: { health: vi.fn() },
  setApiBase: vi.fn(),
}));

import { isTauri, invoke, listen } from "./tauri";
import { api, setApiBase } from "../lib/api";

const mockIsTauri = vi.mocked(isTauri);
const mockInvoke = vi.mocked(invoke);
const mockListen = vi.mocked(listen);
const mockHealth = vi.mocked(api.health);

let handlers: Record<string, (payload: BackendSnapshot) => void>;

beforeEach(() => {
  vi.clearAllMocks();
  handlers = {};
  mockListen.mockImplementation(async (event: string, cb: (p: never) => void) => {
    handlers[event] = cb as (payload: BackendSnapshot) => void;
    return () => {};
  });
});

describe("useBootstrap outside Tauri", () => {
  it("goes straight to ready with a relative api base", async () => {
    mockIsTauri.mockReturnValue(false);
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.state.phase).toBe("ready"));
    expect(setApiBase).toHaveBeenCalledWith("");
    expect(mockListen).not.toHaveBeenCalled();
  });
});

describe("useBootstrap inside Tauri", () => {
  beforeEach(() => {
    mockIsTauri.mockReturnValue(true);
  });

  it("shows port conflict from the initial snapshot", async () => {
    mockInvoke.mockResolvedValue({ state: "port-conflict", port: 8000, message: null });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "port-conflict", port: 8000 }),
    );
  });

  it("sets api base on backend-ready, then polls health to ready", async () => {
    mockInvoke.mockResolvedValue({ state: "starting", port: 8000, message: null });
    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "downloading", version: null, error: null },
    });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(handlers["backend-ready"]).toBeDefined());

    await act(async () => {
      handlers["backend-ready"]({ state: "ready", port: 8123, message: null });
    });
    expect(setApiBase).toHaveBeenCalledWith("http://127.0.0.1:8123");
    await waitFor(() => expect(result.current.state.phase).toBe("downloading-binary"));

    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "ready", version: "135.0", error: null },
    });
    await waitFor(() => expect(result.current.state.phase).toBe("ready"), { timeout: 3000 });
  });

  it("surfaces kernel download errors from health", async () => {
    mockInvoke.mockResolvedValue({ state: "ready", port: 8000, message: null });
    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "error", version: null, error: "disk full" },
    });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "backend-error", message: "disk full" }),
    );
  });

  it("shows backend error and retries via restart_backend", async () => {
    mockInvoke.mockResolvedValue({ state: "error", port: 8000, message: "spawn failed" });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "backend-error", message: "spawn failed" }),
    );

    mockInvoke.mockClear();
    mockInvoke.mockResolvedValue(undefined as never);
    await act(async () => {
      await result.current.retry();
    });
    expect(mockInvoke).toHaveBeenCalledWith("restart_backend");
    expect(result.current.state.phase).toBe("waiting-backend");
  });

  it("savePort invokes save_port and waits for the backend", async () => {
    mockInvoke.mockResolvedValue({ state: "port-conflict", port: 8000, message: null });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.state.phase).toBe("port-conflict"));

    mockInvoke.mockClear();
    mockInvoke.mockResolvedValue(undefined as never);
    await act(async () => {
      await result.current.savePort(8001);
    });
    expect(mockInvoke).toHaveBeenCalledWith("save_port", { port: 8001 });
    expect(result.current.state.phase).toBe("waiting-backend");
  });
});
