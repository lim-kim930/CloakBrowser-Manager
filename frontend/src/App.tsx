import { useState, useCallback } from "react";
import { PanelLeftClose, PanelLeft } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { type ProfileCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { useBootstrap } from "./bootstrap/useBootstrap";
import { PortConfigModal } from "./bootstrap/PortConfigModal";
import { DownloadingScreen } from "./bootstrap/DownloadingScreen";
import { BackendErrorScreen } from "./bootstrap/BackendErrorScreen";

type View = "empty" | "create" | "edit";

export default function App() {
  const { state, probePort, savePort, retry } = useBootstrap();

  switch (state.phase) {
    case "detecting":
      return (
        <div className="h-screen flex items-center justify-center">
          <div className="text-gray-500 text-sm">Loading...</div>
        </div>
      );
    case "port-conflict":
      return <PortConfigModal port={state.port} onProbe={probePort} onSave={savePort} />;
    case "waiting-backend":
      return <DownloadingScreen message="Starting backend service..." />;
    case "downloading-binary":
      return <DownloadingScreen message="Downloading browser core..." />;
    case "backend-error":
      return <BackendErrorScreen message={state.message} onRetry={retry} />;
    case "ready":
      return <AppContent />;
  }
}

function AppContent() {
  const { profiles, loading, error, create, update, remove, launch, stop } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setView("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    await update(selectedId, data);
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    await launch(selectedId);
  }, [selectedId, launch]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
  }, [selectedId, stop]);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
                <span className="text-xs text-gray-500 capitalize">{selected.platform}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {view === "empty" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <p className="text-gray-500 text-sm">Select a profile or create a new one</p>
              </div>
            </div>
          )}

          {view === "create" && (
            <ProfileForm
              profile={null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
            />
          )}

          {view === "edit" && selected && (
            <ProfileForm
              profile={selected}
              onSave={handleUpdate}
              onDelete={handleDelete}
              onCancel={() => {
                setSelectedId(null);
                setView("empty");
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
