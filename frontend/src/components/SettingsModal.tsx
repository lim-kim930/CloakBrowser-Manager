import { useState, useEffect } from "react";
import { api, type BinaryLocation } from "../lib/api";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after the kernel location changed so the app re-polls binary status. */
  onKernelDirChanged: () => void;
}

export function SettingsModal({ open, onClose, onKernelDirChanged }: SettingsModalProps) {
  const [location, setLocation] = useState<BinaryLocation | null>(null);
  const [dir, setDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    api.getBinaryLocation()
      .then((loc) => {
        setLocation(loc);
        setDir(loc.kernel_dir);
      })
      .catch((err: Error) => setError(err.message));
  }, [open]);

  if (!open) return null;

  const canBrowse = Boolean(window.pywebview?.api?.pick_folder);
  const dirty = location !== null && dir.trim() !== "" && dir.trim() !== location.kernel_dir;

  const apply = async (value: string | null) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const loc = await api.setBinaryLocation(value);
      setLocation(loc);
      setDir(loc.kernel_dir);
      setNotice("Location saved. The kernel is re-checked there and downloaded if missing.");
      onKernelDirChanged();
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-1 border border-border rounded-lg p-6 w-[28rem]">
        <h2 className="text-sm font-semibold mb-4">Settings</h2>

        <div className="text-xs font-medium text-gray-300 mb-1">Kernel storage location</div>
        <p className="text-xs text-gray-500 mb-2">
          Where the CloakBrowser kernel is downloaded and loaded from.
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

        <div className="flex items-center justify-between mt-4">
          <button
            className="text-xs text-gray-500 hover:text-gray-300 underline disabled:opacity-50"
            onClick={() => apply(null)}
            disabled={busy || !location || location.is_default}
          >
            Reset to default
          </button>
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={onClose} disabled={busy}>
              Close
            </button>
            <button
              className="btn-primary"
              onClick={() => apply(dir.trim())}
              disabled={busy || !dirty}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
