/**
 * API client for CloakBrowser Manager backend.
 */

export interface Profile {
  id: string;
  name: string;
  fingerprint_seed: number;
  proxy: string | null;
  timezone: string | null;
  locale: string | null;
  platform: string;
  user_agent: string | null;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  hardware_concurrency: number | null;
  humanize: boolean;
  human_preset: string;
  headless: boolean;
  geoip: boolean;
  auto_launch: boolean;
  color_scheme: string | null;
  launch_args: string[];
  notes: string | null;
  user_data_dir: string;
  created_at: string;
  updated_at: string;
  tags: { tag: string; color: string | null }[];
  status: "running" | "stopped";
  cdp_url: string | null;
}

export interface ProfileCreateData {
  name: string;
  fingerprint_seed?: number | null;
  proxy?: string | null;
  timezone?: string | null;
  locale?: string | null;
  platform?: string;
  user_agent?: string | null;
  screen_width?: number;
  screen_height?: number;
  gpu_vendor?: string | null;
  gpu_renderer?: string | null;
  hardware_concurrency?: number | null;
  humanize?: boolean;
  human_preset?: string;
  headless?: boolean;
  geoip?: boolean;
  auto_launch?: boolean;
  color_scheme?: string | null;
  launch_args?: string[];
  notes?: string | null;
  tags?: { tag: string; color: string | null }[];
}

export interface LaunchResult {
  profile_id: string;
  status: string;
  cdp_url: string | null;
}

export interface SystemStatus {
  running_count: number;
  binary_version: string;
  profiles_total: number;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Base URL for all requests. "" in web dev (Vite proxies /api); set to
// "http://127.0.0.1:{port}" by the bootstrap layer under Tauri.
let _base = "";

export function setApiBase(url: string) {
  _base = url.replace(/\/+$/, "");
}

export function getApiBase(): string {
  return _base;
}

export interface BinaryStatus {
  state: "downloading" | "ready" | "error";
  version: string | null;
  error: string | null;
}

export interface Health {
  status: string;
  version: string;
  binary: BinaryStatus;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(_base + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  listProfiles: () => request<Profile[]>("/api/profiles"),

  getProfile: (id: string) => request<Profile>(`/api/profiles/${id}`),

  createProfile: (data: ProfileCreateData) =>
    request<Profile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateProfile: (id: string, data: Partial<ProfileCreateData>) =>
    request<Profile>(`/api/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}`, { method: "DELETE" }),

  launchProfile: (id: string) =>
    request<LaunchResult>(`/api/profiles/${id}/launch`, { method: "POST" }),

  stopProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/stop`, { method: "POST" }),

  getStatus: () => request<SystemStatus>("/api/status"),

  health: () => request<Health>("/api/health"),
};
