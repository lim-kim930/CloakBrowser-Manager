import { useState, useEffect, useCallback } from "react";
import { api, type BinaryLocation, type KernelList } from "../lib/api";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after the kernel location changed so the app re-polls binary status. */
  onKernelDirChanged: () => void;
}

const KERNEL_RELEASES_URL = "https://github.com/CloakHQ/cloakbrowser/releases";

function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function SettingsModal({ open, onClose, onKernelDirChanged }: SettingsModalProps) {
  const [location, setLocation] = useState<BinaryLocation | null>(null);
  const [dir, setDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [kernelList, setKernelList] = useState<KernelList | null>(null);
  const [importSrc, setImportSrc] = useState("");
  const [importVersion, setImportVersion] = useState("");
  const [kernelBusy, setKernelBusy] = useState(false);
  const [kernelError, setKernelError] = useState<string | null>(null);
  const [kernelNotice, setKernelNotice] = useState<string | null>(null);

  const refreshKernels = useCallback(() => {
    return api
      .listKernels()
      .then(setKernelList)
      .catch((err: Error) => setKernelError(err.message));
  }, []);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    setKernelError(null);
    setKernelNotice(null);
    api.getBinaryLocation()
      .then((loc) => {
        setLocation(loc);
        setDir(loc.kernel_dir);
      })
      .catch((err: Error) => setError(err.message));
    refreshKernels();
  }, [open, refreshKernels]);

  if (!open) return null;

  const canBrowse = Boolean(window.pywebview?.api?.pick_folder);
  const canPickFile = Boolean(window.pywebview?.api?.pick_file);
  const dirty = location !== null && dir.trim() !== "" && dir.trim() !== location.kernel_dir;

  const apply = async (value: string | null) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const loc = await api.setBinaryLocation(value);
      setLocation(loc);
      setDir(loc.kernel_dir);
      setNotice("Location saved. Kernels are re-scanned at the new location.");
      onKernelDirChanged();
      await refreshKernels();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const browse = async () => {
    try {
      const picked = await window.pywebview?.api?.pick_folder?.();
      if (picked) setDir(picked);
    } catch {
      // native dialog unavailable — the text input still works
    }
  };

  const pickImportZip = async () => {
    try {
      const picked = await window.pywebview?.api?.pick_file?.(["Zip archive (*.zip)"]);
      if (picked) setImportSrc(picked);
    } catch {
      // native dialog unavailable — the text input still works
    }
  };

  const pickImportFolder = async () => {
    try {
      const picked = await window.pywebview?.api?.pick_folder?.();
      if (picked) setImportSrc(picked);
    } catch {
      // native dialog unavailable — the text input still works
    }
  };

  const runKernelAction = async (action: () => Promise<KernelList>, doneNotice: string) => {
    setKernelBusy(true);
    setKernelError(null);
    setKernelNotice(null);
    try {
      const list = await action();
      setKernelList(list);
      setKernelNotice(doneNotice);
      onKernelDirChanged();
    } catch (err) {
      setKernelError(err instanceof Error ? err.message : String(err));
    } finally {
      setKernelBusy(false);
    }
  };

  const importKernel = () => {
    const src = importSrc.trim();
    if (!src) return;
    return runKernelAction(
      () => api.importKernel(src, importVersion.trim() || undefined),
      "Kernel imported.",
    ).then(() => {
      setImportSrc("");
      setImportVersion("");
    });
  };

  const deleteKernel = (version: string) => {
    if (!confirm(`Delete kernel ${version} from disk?`)) return;
    return runKernelAction(() => api.deleteKernel(version), `Kernel ${version} deleted.`);
  };

  const setDefault = (version: string | null) => {
    return runKernelAction(
      () => api.setDefaultKernel(version),
      version ? `Default kernel set to ${version}.` : "Default kernel cleared (newest wins).",
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-1 border border-border rounded-lg p-6 w-[30rem] max-h-[85vh] overflow-y-auto">
        <h2 className="text-sm font-semibold mb-4">Settings</h2>

        <div className="text-xs font-medium text-gray-300 mb-1">Kernel storage location</div>
        <p className="text-xs text-gray-500 mb-2">
          Where installed CloakBrowser kernels live and are loaded from.
        </p>
        <div className="flex gap-2 mb-2">
          <input
            type="text"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            disabled={busy || location === null}
            className="input flex-1"
            placeholder={location?.default_kernel_dir ?? "Loading..."}
            aria-label="Kernel storage location"
          />
          {canBrowse && (
            <button className="btn-secondary" onClick={browse} disabled={busy}>
              Browse…
            </button>
          )}
        </div>

        {error && <p className="text-xs text-red-400 mb-2">{error}</p>}
        {notice && <p className="text-xs text-emerald-400 mb-2">{notice}</p>}

        <div className="flex items-center justify-between mb-5">
          <button
            className="text-xs text-gray-500 hover:text-gray-300 underline disabled:opacity-50"
            onClick={() => apply(null)}
            disabled={busy || !location || location.is_default}
          >
            Reset to default
          </button>
          <button
            className="btn-primary"
            onClick={() => apply(dir.trim())}
            disabled={busy || !dirty}
          >
            Save
          </button>
        </div>

        <div className="border-t border-border pt-4">
          <div className="text-xs font-medium text-gray-300 mb-1">Browser kernels</div>
          <p className="text-xs text-gray-500 mb-2">
            Download a kernel yourself from the{" "}
            <a
              href={KERNEL_RELEASES_URL}
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-gray-300"
            >
              releases page
            </a>
            , then import the .zip or extracted folder here. The release tag
            (chromium-v…) is the version.
          </p>

          {kernelList && kernelList.kernels.length > 0 ? (
            <div className="mb-3 space-y-1" role="list" aria-label="Installed kernels">
              <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer py-0.5">
                <input
                  type="radio"
                  name="default-kernel"
                  checked={kernelList.default_version === null}
                  onChange={() => setDefault(null)}
                  disabled={kernelBusy}
                />
                <span>Auto (newest installed is the default)</span>
              </label>
              {kernelList.kernels.map((k) => (
                <div key={k.version} className="flex items-center gap-2 py-0.5" role="listitem">
                  <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer flex-1 min-w-0">
                    <input
                      type="radio"
                      name="default-kernel"
                      checked={kernelList.default_version === k.version}
                      onChange={() => setDefault(k.version)}
                      disabled={kernelBusy}
                      aria-label={`Set ${k.version} as default`}
                    />
                    <span className="truncate font-mono text-xs">{k.version}</span>
                    {k.in_use && (
                      <span className="text-[10px] uppercase tracking-wide text-emerald-400">
                        in use
                      </span>
                    )}
                  </label>
                  <span className="text-xs text-gray-500 whitespace-nowrap">
                    {formatSize(k.size)}
                  </span>
                  <button
                    className="btn-danger text-xs"
                    onClick={() => deleteKernel(k.version)}
                    disabled={kernelBusy || k.in_use}
                    title={k.in_use ? "Stop the running profile(s) first" : undefined}
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-amber-400 mb-3">
              No kernels installed yet — import one below to launch profiles.
            </p>
          )}

          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={importSrc}
              onChange={(e) => setImportSrc(e.target.value)}
              disabled={kernelBusy}
              className="input flex-1"
              placeholder="Path to downloaded .zip or extracted folder"
              aria-label="Kernel source path"
            />
            {canPickFile && (
              <button className="btn-secondary" onClick={pickImportZip} disabled={kernelBusy}>
                Zip…
              </button>
            )}
            {canBrowse && (
              <button className="btn-secondary" onClick={pickImportFolder} disabled={kernelBusy}>
                Folder…
              </button>
            )}
          </div>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={importVersion}
              onChange={(e) => setImportVersion(e.target.value)}
              disabled={kernelBusy}
              className="input flex-1 font-mono"
              placeholder="Version, e.g. 146.0.7680.177.5 (auto from chromium-… folder)"
              aria-label="Kernel version"
            />
            <button
              className="btn-primary"
              onClick={importKernel}
              disabled={kernelBusy || !importSrc.trim()}
            >
              {kernelBusy ? "Working…" : "Import"}
            </button>
          </div>

          {kernelError && <p className="text-xs text-red-400 mb-2">{kernelError}</p>}
          {kernelNotice && <p className="text-xs text-emerald-400 mb-2">{kernelNotice}</p>}
        </div>

        <div className="flex justify-end mt-4">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
