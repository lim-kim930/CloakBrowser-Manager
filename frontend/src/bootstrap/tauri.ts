/**
 * Thin wrappers around @tauri-apps/api so the app also runs in a plain
 * browser (pnpm dev) where the Tauri IPC bridge doesn't exist. Dynamic
 * imports keep Tauri modules out of the pure-web bundle path at runtime.
 */

export interface BackendSnapshot {
  state: "starting" | "port-conflict" | "ready" | "error";
  port: number;
  message: string | null;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function listen<T>(
  event: string,
  handler: (payload: T) => void,
): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<T>(event, (e) => handler(e.payload));
}

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}
