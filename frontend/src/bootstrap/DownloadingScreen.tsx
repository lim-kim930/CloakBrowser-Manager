import { Loader2 } from "lucide-react";

interface DownloadingScreenProps {
  message: string;
}

export function DownloadingScreen({ message }: DownloadingScreenProps) {
  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="text-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent mx-auto mb-3" />
        <p className="text-sm text-gray-300">{message}</p>
        <p className="text-xs text-gray-500 mt-1">This can take a few minutes on first run</p>
      </div>
    </div>
  );
}
