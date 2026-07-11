import { useState } from "react";
import { Code2, Monitor } from "lucide-react";

interface RunningPanelProps {
  profileId: string;
  cdpUrl: string | null;
}

export function RunningPanel({ profileId: _profileId, cdpUrl }: RunningPanelProps) {
  const [cdpCopied, setCdpCopied] = useState(false);

  const copyCdp = () => {
    if (!cdpUrl) return;
    const abs = `${window.location.protocol}//${window.location.host}${cdpUrl}`;
    navigator.clipboard
      ?.writeText(abs)
      .then(() => {
        setCdpCopied(true);
        setTimeout(() => setCdpCopied(false), 2000);
      })
      .catch((err) => console.warn("[cdp] copy failed:", err));
  };

  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md px-6">
        <div className="flex items-center justify-center mb-4">
          <span className="relative inline-flex h-3 w-3 mr-2">
            <span className="absolute inline-flex h-3 w-3 rounded-full bg-emerald-400 opacity-75 animate-ping" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-400" />
          </span>
          <span className="text-sm font-medium text-gray-200">Running</span>
        </div>

        <Monitor className="h-10 w-10 mx-auto text-gray-500 mb-3" />
        <p className="text-sm text-gray-300 mb-1">
          The browser window is open on your desktop.
        </p>
        <p className="text-xs text-gray-500 mb-6">
          Closing that window (or clicking Stop) ends this session.
        </p>

        {cdpUrl && (
          <button
            onClick={copyCdp}
            aria-label="Copy CDP endpoint"
            className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border ${
              cdpCopied ? "text-emerald-400" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <Code2 className="h-3.5 w-3.5" />
            {cdpCopied ? "Copied!" : "Copy CDP endpoint"}
          </button>
        )}
      </div>
    </div>
  );
}
