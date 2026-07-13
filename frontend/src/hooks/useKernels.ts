import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DownloadStatus, type Kernel } from "../lib/api";

const DOWNLOAD_POLL_MS = 1000;

export function useKernels() {
  const [kernels, setKernels] = useState<Kernel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadState, setDownloadState] = useState<DownloadStatus>({
    state: "idle",
    error: null,
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setKernels(await api.listKernels());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load kernels");
    } finally {
      setLoading(false);
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    void refresh();
    return stopPolling;
  }, [refresh, stopPolling]);

  const startDownload = useCallback(async () => {
    try {
      await api.downloadKernel();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed to start");
      return;
    }
    setDownloadState({ state: "downloading", error: null });
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.downloadStatus();
        setDownloadState(status);
        if (status.state === "ready" || status.state === "error") {
          stopPolling();
          void refresh();
        }
      } catch {
        // transient — keep polling
      }
    }, DOWNLOAD_POLL_MS);
  }, [refresh, stopPolling]);

  const importKernel = useCallback(
    async (path: string) => {
      try {
        await api.importKernel(path);
        setError(null);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Import failed");
      }
    },
    [refresh],
  );

  const setDefault = useCallback(
    async (id: string) => {
      try {
        await api.setDefaultKernel(id);
        setError(null);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to set default");
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.deleteKernel(id);
        setError(null);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Delete failed");
      }
    },
    [refresh],
  );

  return {
    kernels,
    loading,
    error,
    downloadState,
    refresh,
    importKernel,
    startDownload,
    setDefault,
    remove,
  };
}
