import { useState } from "react";

interface CloseModalProps {
  open: boolean;
  onChoice: (choice: "exit" | "tray" | "cancel", remember: boolean) => void;
}

export function CloseModal({ open, onChoice }: CloseModalProps) {
  const [remember, setRemember] = useState(false);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-1 border border-border rounded-lg p-6 w-80">
        <h2 className="text-sm font-semibold mb-2">Close CloakBrowser Manager?</h2>
        <p className="text-xs text-gray-400 mb-4">
          Browsers are still running. What should happen?
        </p>

        <label className="flex items-center gap-2 text-xs text-gray-300 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="rounded border-border bg-surface-2"
          />
          Remember my choice
        </label>

        <div className="flex flex-col gap-2">
          <button
            className="btn-danger"
            onClick={() => onChoice("exit", remember)}
          >
            Quit and close all browsers
          </button>
          <button
            className="btn-secondary"
            onClick={() => onChoice("tray", remember)}
          >
            Minimize to tray
          </button>
          <button
            className="btn-secondary"
            onClick={() => onChoice("cancel", false)}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
