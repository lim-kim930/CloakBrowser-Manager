import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SettingsModal } from "./SettingsModal";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    getBinaryLocation: vi.fn(),
    setBinaryLocation: vi.fn(),
    listKernels: vi.fn(),
    importKernel: vi.fn(),
    deleteKernel: vi.fn(),
    setDefaultKernel: vi.fn(),
  },
}));

const DEFAULT_LOC = {
  kernel_dir: "C:\\Users\\me\\.cloakbrowser",
  default_kernel_dir: "C:\\Users\\me\\.cloakbrowser",
  is_default: true,
};

const EMPTY_KERNELS = {
  kernels: [],
  default_version: null,
  kernel_dir: DEFAULT_LOC.kernel_dir,
};

const TWO_KERNELS = {
  kernels: [
    {
      version: "148.0.7778.215.2",
      path: "C:\\k\\chromium-148.0.7778.215.2",
      size: 250 * 1024 ** 2,
      pro: false,
      in_use: false,
    },
    {
      version: "146.0.7680.177.5",
      path: "C:\\k\\chromium-146.0.7680.177.5",
      size: 245 * 1024 ** 2,
      pro: false,
      in_use: true,
    },
  ],
  default_version: "146.0.7680.177.5",
  kernel_dir: DEFAULT_LOC.kernel_dir,
};

beforeEach(() => {
  vi.mocked(api.getBinaryLocation).mockResolvedValue({ ...DEFAULT_LOC });
  vi.mocked(api.setBinaryLocation).mockReset();
  vi.mocked(api.listKernels).mockResolvedValue({ ...EMPTY_KERNELS });
  vi.mocked(api.importKernel).mockReset();
  vi.mocked(api.deleteKernel).mockReset();
  vi.mocked(api.setDefaultKernel).mockReset();
});

afterEach(() => {
  delete window.pywebview;
  vi.restoreAllMocks();
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

describe("SettingsModal kernels section", () => {
  it("shows an empty-state hint when nothing is installed", async () => {
    renderModal();
    expect(await screen.findByText(/no kernels installed yet/i)).toBeInTheDocument();
  });

  it("lists installed kernels with size, default and in-use markers", async () => {
    vi.mocked(api.listKernels).mockResolvedValue({ ...TWO_KERNELS });
    renderModal();

    expect(await screen.findByText("148.0.7778.215.2")).toBeInTheDocument();
    expect(screen.getByText("146.0.7680.177.5")).toBeInTheDocument();
    expect(screen.getByText("250 MB")).toBeInTheDocument();
    expect(screen.getByText(/in use/i)).toBeInTheDocument();
    // configured default is checked
    expect(
      screen.getByRole("radio", { name: /set 146\.0\.7680\.177\.5 as default/i }),
    ).toBeChecked();
  });

  it("imports from a typed path with an explicit version", async () => {
    const onKernelDirChanged = vi.fn();
    vi.mocked(api.importKernel).mockResolvedValue({ ...TWO_KERNELS });
    renderModal({ onKernelDirChanged });

    fireEvent.change(await screen.findByLabelText(/kernel source path/i), {
      target: { value: "D:\\Downloads\\kernel.zip" },
    });
    fireEvent.change(screen.getByLabelText(/kernel version/i), {
      target: { value: "146.0.7680.177.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /import/i }));

    await waitFor(() =>
      expect(api.importKernel).toHaveBeenCalledWith(
        "D:\\Downloads\\kernel.zip",
        "146.0.7680.177.5",
      ),
    );
    expect(onKernelDirChanged).toHaveBeenCalled();
    expect(await screen.findByText(/kernel imported/i)).toBeInTheDocument();
  });

  it("surfaces the backend error when import needs a version", async () => {
    vi.mocked(api.importKernel).mockRejectedValue(
      new Error("Kernel version is required when importing an archive"),
    );
    renderModal();

    fireEvent.change(await screen.findByLabelText(/kernel source path/i), {
      target: { value: "D:\\Downloads\\kernel.zip" },
    });
    fireEvent.click(screen.getByRole("button", { name: /import/i }));

    expect(await screen.findByText(/version is required/i)).toBeInTheDocument();
  });

  it("fills the source path from the native zip picker", async () => {
    window.pywebview = {
      api: {
        pick_folder: vi.fn(),
        pick_file: vi.fn().mockResolvedValue("D:\\Downloads\\kernel.zip"),
      },
    };
    renderModal();

    fireEvent.click(await screen.findByRole("button", { name: /zip…/i }));
    await waitFor(() =>
      expect(screen.getByLabelText(/kernel source path/i)).toHaveValue(
        "D:\\Downloads\\kernel.zip",
      ),
    );
    expect(window.pywebview.api?.pick_file).toHaveBeenCalledWith(["Zip archive (*.zip)"]);
  });

  it("deletes a kernel after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.listKernels).mockResolvedValue({ ...TWO_KERNELS });
    vi.mocked(api.deleteKernel).mockResolvedValue({ ...EMPTY_KERNELS });
    renderModal();

    const deleteButtons = await screen.findAllByRole("button", { name: /delete/i });
    fireEvent.click(deleteButtons[0]); // newest (148…) is not in use
    await waitFor(() =>
      expect(api.deleteKernel).toHaveBeenCalledWith("148.0.7778.215.2"),
    );
  });

  it("disables delete for a kernel in use", async () => {
    vi.mocked(api.listKernels).mockResolvedValue({ ...TWO_KERNELS });
    renderModal();

    const deleteButtons = await screen.findAllByRole("button", { name: /delete/i });
    expect(deleteButtons[1]).toBeDisabled(); // 146… is in_use
  });

  it("changes the default kernel via the radios", async () => {
    vi.mocked(api.listKernels).mockResolvedValue({ ...TWO_KERNELS });
    vi.mocked(api.setDefaultKernel).mockResolvedValue({
      ...TWO_KERNELS,
      default_version: null,
    });
    renderModal();

    fireEvent.click(await screen.findByRole("radio", { name: /auto \(newest/i }));
    await waitFor(() => expect(api.setDefaultKernel).toHaveBeenCalledWith(null));
  });
});
