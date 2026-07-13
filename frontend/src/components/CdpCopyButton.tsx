import { Check, Link } from "lucide-react";
import { useState } from "react";
import { getApiBase } from "../lib/api";

interface CdpCopyButtonProps {
  cdpUrl: string; // relative path like /api/profiles/<id>/cdp
}

export function CdpCopyButton({ cdpUrl }: CdpCopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const url = `${getApiBase() || window.location.origin}${cdpUrl}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // WebView clipboard-API fallback
      const ta = document.createElement("textarea");
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="btn-secondary flex items-center gap-1.5"
      title="Copy the CDP endpoint for Playwright/Puppeteer connect_over_cdp"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Link className="h-3.5 w-3.5" />}
      <span>{copied ? "Copied" : "Copy CDP URL"}</span>
    </button>
  );
}
