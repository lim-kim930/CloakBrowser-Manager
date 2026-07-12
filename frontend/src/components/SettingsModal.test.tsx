import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SettingsModal } from "./SettingsModal";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    getBinaryLocation: vi.fn(),
    setBinaryLocation: vi.fn(),
  },
}));

const DEFAULT_LOC = {
  kernel_dir: "C:\\Users\\me\\.cloakbrowser",
  default_kernel_dir: "C:\\Users\\me\\.cloakbrowser",
  is_default: true,
};

beforeEach(() => {
  vi.mocked(api.getBinaryLocation).mockResolvedValue({ ...DEFAULT_LOC });
  vi.mocked(api.setBinaryLocation).mockReset();
});

afterEach(() => {
  delete window.pywebview;
});

function renderModal(overrides: Partial<Parameters<typeof SettingsModal>[0]> = {}) {
  return render(
    <SettingsModal open onClose={vi.fn()} onKernelDirChanged={vi.fn()} {...overrides} />,
  );
}

describe("SettingsModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <SettingsModal open={false} onClose={vi.fn()} onKernelDirChanged={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("loads and shows the current kernel location", async () => {
    renderModal();
    await waitFor(() =>
      expect(screen.getByLabelText(/kernel storage location/i)).toHaveValue(DEFAULT_LOC.kernel_dir),
    );
  });

  it("saves an edited path and notifies for a re-poll", async () => {
    const onKernelDirChanged = vi.fn();
    vi.mocked(api.setBinaryLocation).mockResolvedValue({
      kernel_dir: "D:\\kernels",
      default_kernel_dir: DEFAULT_LOC.default_kernel_dir,
      is_default: false,
    });
    renderModal({ onKernelDirChanged });

    const input = await screen.findByLabelText(/kernel storage location/i);
    await waitFor(() => expect(input).toHaveValue(DEFAULT_LOC.kernel_dir));
    fireEvent.change(input, { target: { value: "D:\\kernels" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(api.setBinaryLocation).toHaveBeenCalledWith("D:\\kernels"));
    expect(onKernelDirChanged).toHaveBeenCalled();
    expect(await screen.findByText(/location saved/i)).toBeInTheDocument();
  });

  it("save is disabled until the path is edited", async () => {
    renderModal();
    await waitFor(() =>
      expect(screen.getByLabelText(/kernel storage location/i)).toHaveValue(DEFAULT_LOC.kernel_dir),
    );
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("reset to default sends null and is disabled when already default", async () => {
    vi.mocked(api.getBinaryLocation).mockResolvedValue({
      kernel_dir: "D:\\kernels",
      default_kernel_dir: DEFAULT_LOC.default_kernel_dir,
      is_default: false,
    });
    vi.mocked(api.setBinaryLocation).mockResolvedValue({ ...DEFAULT_LOC });
    renderModal();

    const reset = await screen.findByRole("button", { name: /reset to default/i });
    await waitFor(() => expect(reset).toBeEnabled());
    fireEvent.click(reset);

    await waitFor(() => expect(api.setBinaryLocation).toHaveBeenCalledWith(null));
    await waitFor(() => expect(screen.getByRole("button", { name: /reset to default/i })).toBeDisabled());
  });

  it("shows the backend error message when saving fails", async () => {
    vi.mocked(api.setBinaryLocation).mockRejectedValue(
      new Error("Kernel location must be an absolute path"),
    );
    renderModal();

    const input = await screen.findByLabelText(/kernel storage location/i);
    await waitFor(() => expect(input).toHaveValue(DEFAULT_LOC.kernel_dir));
    fireEvent.change(input, { target: { value: "relative\\dir" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText(/absolute path/i)).toBeInTheDocument();
  });

  it("hides Browse without the pywebview bridge", async () => {
    renderModal();
    await screen.findByLabelText(/kernel storage location/i);
    expect(screen.queryByRole("button", { name: /browse/i })).toBeNull();
  });

  it("Browse fills the input from the native folder picker", async () => {
    window.pywebview = { api: { pick_folder: vi.fn().mockResolvedValue("E:\\picked") } };
    renderModal();

    const input = await screen.findByLabelText(/kernel storage location/i);
    await waitFor(() => expect(input).toHaveValue(DEFAULT_LOC.kernel_dir));
    fireEvent.click(screen.getByRole("button", { name: /browse/i }));
    await waitFor(() => expect(input).toHaveValue("E:\\picked"));
  });
});
