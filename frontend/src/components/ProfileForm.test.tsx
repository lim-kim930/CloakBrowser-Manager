import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProfileForm } from "./ProfileForm";
import { api } from "../lib/api";
import type { Profile } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    listKernels: vi.fn(),
  },
}));

const KERNELS = {
  kernels: [
    {
      version: "148.0.7778.215.2",
      path: "C:\\k\\chromium-148.0.7778.215.2",
      size: 1000,
      pro: false,
      in_use: false,
    },
    {
      version: "146.0.7680.177.5",
      path: "C:\\k\\chromium-146.0.7680.177.5",
      size: 1000,
      pro: false,
      in_use: false,
    },
  ],
  default_version: null,
  kernel_dir: "C:\\k",
};

function makeProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: "p1",
    name: "Existing",
    fingerprint_seed: 12345,
    proxy: null,
    timezone: null,
    locale: null,
    platform: "windows",
    user_agent: null,
    screen_width: 1920,
    screen_height: 1080,
    gpu_vendor: null,
    gpu_renderer: null,
    hardware_concurrency: null,
    humanize: false,
    human_preset: "default",
    headless: false,
    geoip: false,
    clipboard_sync: true,
    auto_launch: false,
    color_scheme: null,
    launch_args: [],
    notes: null,
    kernel_version: null,
    user_data_dir: "/data/profiles/p1",
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    tags: [],
    status: "stopped",
    vnc_ws_port: null,
    cdp_url: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.listKernels).mockResolvedValue({ ...KERNELS });
});

describe("ProfileForm kernel selector", () => {
  it("lists installed kernels with a Default option showing the newest", async () => {
    render(<ProfileForm profile={null} onSave={vi.fn()} onCancel={vi.fn()} />);

    const select = await screen.findByLabelText(/browser kernel/i);
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "146.0.7680.177.5" })).toBeInTheDocument(),
    );
    expect(select).toHaveValue("");
    // No default set → Default resolves to the newest installed
    expect(
      screen.getByRole("option", { name: /default \(148\.0\.7778\.215\.2\)/i }),
    ).toBeInTheDocument();
  });

  it("shows the configured default version in the Default label", async () => {
    vi.mocked(api.listKernels).mockResolvedValue({
      ...KERNELS,
      default_version: "146.0.7680.177.5",
    });
    render(<ProfileForm profile={null} onSave={vi.fn()} onCancel={vi.fn()} />);
    expect(
      await screen.findByRole("option", { name: /default \(146\.0\.7680\.177\.5\)/i }),
    ).toBeInTheDocument();
  });

  it("submits the selected kernel_version", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} onSave={onSave} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/amazon seller/i), {
      target: { value: "My Profile" },
    });
    const select = await screen.findByLabelText(/browser kernel/i);
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "146.0.7680.177.5" })).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: "146.0.7680.177.5" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({
      name: "My Profile",
      kernel_version: "146.0.7680.177.5",
    });
  });

  it("hydrates the pinned version when editing", async () => {
    render(
      <ProfileForm
        profile={makeProfile({ kernel_version: "146.0.7680.177.5" })}
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const select = await screen.findByLabelText(/browser kernel/i);
    await waitFor(() => expect(select).toHaveValue("146.0.7680.177.5"));
  });

  it("keeps an uninstalled pin visible as a disabled option", async () => {
    render(
      <ProfileForm
        profile={makeProfile({ kernel_version: "9.9.9.9" })}
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const missing = await screen.findByRole("option", {
      name: /9\.9\.9\.9 \(not installed\)/i,
    });
    expect(missing).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByLabelText(/browser kernel/i)).toHaveValue("9.9.9.9"),
    );
  });

  it("still renders with only the Default option when the kernel list fails", async () => {
    vi.mocked(api.listKernels).mockRejectedValue(new Error("boom"));
    render(<ProfileForm profile={null} onSave={vi.fn()} onCancel={vi.fn()} />);
    const select = await screen.findByLabelText(/browser kernel/i);
    expect(select).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /default \(no kernel installed\)/i }),
    ).toBeInTheDocument();
  });
});
