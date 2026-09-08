// Toast — auto-dismissing notification. Intentionally race-prone: it disappears
// after 3000ms which gives Playwright a real timing-sensitive element to catch
// (scenario 4 — flake quarantine — needs a genuine timing-sensitive target).
// This component is dynamically created in the DOM by showToast(); no stable
// anchor for a static locator → flagged-unstable by the locator-explorer.
import React, { useEffect, useState } from "react";

interface ToastProps {
  message: string;
  onDone: () => void;
  durationMs?: number;
}

export function Toast({ message, onDone, durationMs = 3000 }: ToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      onDone();
    }, durationMs);
    return () => clearTimeout(timer);
  }, [durationMs, onDone]);

  if (!visible) return null;

  return (
    <div
      id="toast-container"
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        bottom: "20px",
        right: "20px",
        background: "#333",
        color: "white",
        padding: "10px 20px",
        borderRadius: "5px",
        zIndex: 1000,
      }}
    >
      {message}
    </div>
  );
}

// Hook that manages toast state — consumers call showToast(msg)
export function useToast() {
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => setToast(msg);
  const clearToast = () => setToast(null);

  const ToastComponent = toast ? (
    <Toast message={toast} onDone={clearToast} />
  ) : null;

  return { showToast, ToastComponent };
}
