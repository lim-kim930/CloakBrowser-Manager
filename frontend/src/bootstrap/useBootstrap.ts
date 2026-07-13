import { useCallback, useEffect, useRef, useState } from "react";
import { api, setApiBase } from "../lib/api";
import { invoke, isTauri, listen, type BackendSnapshot } from "./tauri";

export type BootstrapPhase =
  | { phase: "detecting" }
  | { phase: "port-conflict"; port: number }
  | { phase: "waiting-backend" }
  | { phase: "downloading-binary" }
  | { phase: "ready" }
  | { phase: "backend-error"; message: string };

const HEALTH_POLL_MS = 1000;

/**
 * Startup state machine. Outside Tauri (pnpm dev) it short-circuits to
 * ready with a relative api base. Inside Tauri it follows the Rust shell:
 * events for live updates + a get_backend_state snapshot to catch anything
 * emitted before our listeners attached.
 */
export function useBootstrap() {
  const [state, setState] = useState<BootstrapPhase>({ phase: "detecting" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Backend reachable → wait until the Chromium kernel is ready too.
  const startHealthPolling = useCallback(() => {
    stopPolling();
    const tick = async () => {
      try {
        const health = await api.health();
        if (health.binary.state === "ready") {
          stopPolling();
          setState({ phase: "ready" });
        } else if (health.binary.state === "error") {
          stopPolling();
          setState({
            phase: "backend-error",
            message: health.binary.error ?? "Browser core download failed",
          });
        } else {
          setState({ phase: "downloading-binary" });
        }
      } catch {
        // transient — keep polling; the Rust shell reports hard failures
      }
    };
    void tick();
    pollRef.current = setInterval(tick, HEALTH_POLL_MS);
  }, [stopPolling]);

  const applySnapshot = useCallback(
    (snap: BackendSnapshot) => {
      if (snap.state === "port-conflict") {
        stopPolling();
        setState({ phase: "port-conflict", port: snap.port });
      } else if (snap.state === "error") {
        stopPolling();
        setState({ phase: "backend-error", message: snap.message ?? "Backend failed to start" });
      } else if (snap.state === "ready") {
        setApiBase(`http://127.0.0.1:${snap.port}`);
        setState({ phase: "waiting-backend" });
        startHealthPolling();
      } else {
        setState({ phase: "waiting-backend" });
      }
    },
    [startHealthPolling, stopPolling],
  );

  useEffect(() => {
    if (!isTauri()) {
      // Plain web dev: relative base, Vite proxies /api → localhost:8000.
      setApiBase("");
      setState({ phase: "ready" });
      return;
    }
    let disposed = false;
    const unlistens: Array<() => void> = [];
    (async () => {
      for (const event of ["backend-starting", "port-conflict", "backend-ready", "backend-error"]) {
        const un = await listen<BackendSnapshot>(event, (snap) => {
          if (!disposed) applySnapshot(snap);
        });
        unlistens.push(un);
      }
      // Catch up on state set before our listeners attached.
      const snap = await invoke<BackendSnapshot>("get_backend_state");
      if (!disposed) applySnapshot(snap);
    })();
    return () => {
      disposed = true;
      unlistens.forEach((un) => un());
      stopPolling();
    };
  }, [applySnapshot, stopPolling]);

  const probePort = useCallback((port: number) => invoke<boolean>("probe_port", { port }), []);

  const savePort = useCallback(async (port: number) => {
    await invoke("save_port", { port });
    setState({ phase: "waiting-backend" });
  }, []);

  const retry = useCallback(async () => {
    setState({ phase: "waiting-backend" });
    await invoke("restart_backend");
  }, []);

  return { state, probePort, savePort, retry };
}
