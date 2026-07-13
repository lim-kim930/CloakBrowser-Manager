import { isTauri } from "../bootstrap/tauri";

/** Native folder picker under Tauri; plain-text prompt in web dev. */
export async function pickFolder(): Promise<string | null> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  }
  return window.prompt("Kernel directory path:") ?? null;
}
