// ConfirmDialog — reusable confirmation modal.
// data-testid values "confirm-delete-button" and "cancel-delete-button" are hardcoded
// in the golden suite (scenario 5's filter logic) and MUST NOT be changed.
import React from "react";

interface ConfirmDialogProps {
  isOpen: boolean;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  isOpen,
  message,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirm action"
      style={{
        position: "fixed",
        top: "30%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        background: "white",
        border: "1px solid black",
        padding: "20px",
        zIndex: 1000,
        boxShadow: "0 4px 8px rgba(0,0,0,0.2)",
      }}
    >
      <p>{message}</p>
      <button data-testid="confirm-delete-button" onClick={onConfirm}>
        Confirm
      </button>
      <button data-testid="cancel-delete-button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
