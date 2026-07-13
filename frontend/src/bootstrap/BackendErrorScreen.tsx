import { AlertCircle } from "lucide-react";

interface BackendErrorScreenProps {
  message: string;
  onRetry: () => void;
}

export function BackendErrorScreen({ message, onRetry }: BackendErrorScreenProps) {
  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="text-center max-w-md px-6">
        <AlertCircle className="h-6 w-6 text-red-400 mx-auto mb-3" />
        <p className="text-sm text-red-400 mb-1">Backend error</p>
        <p className="text-xs text-gray-500 break-words mb-4">{message}</p>
        <button onClick={onRetry} className="btn-secondary">
          Retry
        </button>
      </div>
    </div>
  );
}
