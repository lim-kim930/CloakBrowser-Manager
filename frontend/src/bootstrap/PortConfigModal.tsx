import { AlertTriangle } from "lucide-react";
import { useState } from "react";

interface PortConfigModalProps {
  port: number; // the port that was found occupied
  onProbe: (port: number) => Promise<boolean>;
  onSave: (port: number) => Promise<void>;
}

export function PortConfigModal({ port, onProbe, onSave }: PortConfigModalProps) {
  const [value, setValue] = useState(String(port));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const candidate = Number(value);
    if (!Number.isInteger(candidate) || candidate < 1024 || candidate > 65535) {
      setError("Enter a port between 1024 and 65535");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const free = await onProbe(candidate);
      if (!free) {
        setError(`Port ${candidate} is also in use — try another`);
        return;
      }
      await onSave(candidate);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <form onSubmit={handleSubmit} className="w-96 p-6 rounded-lg border border-border bg-surface-1">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold">Port {port} is in use</h2>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Another program is using the API port. Choose a different port for the backend.
        </p>
        <label className="label">API Port</label>
        <input
          className="input"
          type="number"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          min={1024}
          max={65535}
        />
        {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
        <button type="submit" disabled={busy} className="btn-primary w-full mt-4">
          {busy ? "Checking..." : "Use this port"}
        </button>
      </form>
    </div>
  );
}
