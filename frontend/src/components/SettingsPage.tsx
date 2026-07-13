import { Download, FolderOpen, Star, Trash2, TriangleAlert } from "lucide-react";
import type { useKernels } from "../hooks/useKernels";
import { pickFolder } from "../lib/pickFolder";

interface SettingsPageProps {
  kernelLib: ReturnType<typeof useKernels>;
}

export function SettingsPage({ kernelLib }: SettingsPageProps) {
  const { kernels, loading, error, downloadState, importKernel, startDownload, setDefault, remove } = kernelLib;

  const handleImport = async () => {
    const path = await pickFolder();
    if (path) await importKernel(path);
  };

  const handleDelete = (id: string, version: string) => {
    if (!confirm(`Remove kernel ${version} from the library?`)) return;
    void remove(id);
  };

  const downloading = downloadState.state === "downloading";

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h2 className="text-lg font-semibold mb-6">Settings</h2>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Browser Kernels
          </h3>
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleImport} className="btn-secondary flex items-center gap-1.5">
              <FolderOpen className="h-3.5 w-3.5" />
              <span>Import…</span>
            </button>
            <button
              type="button"
              onClick={() => void startDownload()}
              disabled={downloading}
              className="btn-primary flex items-center gap-1.5"
            >
              <Download className="h-3.5 w-3.5" />
              <span>{downloading ? "Downloading…" : "Download recommended"}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="px-3 py-2 mb-3 rounded bg-red-600/15 border border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}
        {downloadState.state === "error" && downloadState.error && (
          <div className="px-3 py-2 mb-3 rounded bg-red-600/15 border border-red-600/30 text-red-400 text-sm">
            Download failed: {downloadState.error}
          </div>
        )}
        {downloading && (
          <div className="px-3 py-2 mb-3 rounded bg-surface-2 text-sm text-gray-300">
            Downloading browser kernel… this can take a few minutes.
          </div>
        )}

        {loading ? (
          <div className="text-gray-500 text-sm">Loading…</div>
        ) : kernels.length === 0 ? (
          <div className="text-gray-500 text-sm py-6 text-center border border-dashed border-border rounded">
            No kernels yet. Import a downloaded kernel directory or download the recommended version.
          </div>
        ) : (
          <ul className="space-y-2">
            {kernels.map((k) => (
              <li key={k.id} className="flex items-center gap-3 px-3 py-2 rounded bg-surface-1 border border-border">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium font-mono">{k.version}</span>
                    <span className="text-xs text-gray-500 capitalize">{k.source}</span>
                    {k.is_default && (
                      <span className="text-xs px-1.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                        default
                      </span>
                    )}
                    {!k.valid && (
                      <span className="inline-flex items-center gap-1 text-xs text-red-400">
                        <TriangleAlert className="h-3 w-3" /> missing on disk
                      </span>
                    )}
                  </div>
                  {k.source_path && (
                    <div className="text-xs text-gray-500 truncate">{k.source_path}</div>
                  )}
                  <div className="text-xs text-gray-500">
                    {k.profile_count} profile{k.profile_count === 1 ? "" : "s"}
                  </div>
                </div>
                {!k.is_default && k.valid && (
                  <button
                    type="button"
                    onClick={() => void setDefault(k.id)}
                    className="btn-secondary flex items-center gap-1 text-xs"
                    title="Set as default kernel"
                  >
                    <Star className="h-3 w-3" /> Set default
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleDelete(k.id, k.version)}
                  className="btn-danger flex items-center gap-1 text-xs"
                  aria-label={`Delete kernel ${k.version}`}
                >
                  <Trash2 className="h-3 w-3" /> Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
