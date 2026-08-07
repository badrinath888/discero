import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ConfirmationModal from "./ConfirmationModal";

function renderModal(overrides: Partial<Parameters<typeof ConfirmationModal>[0]> = {}) {
  const onCancel = vi.fn();
  const onConfirm = vi.fn();

  render(
    <ConfirmationModal
      eyebrow="Confirm deletion"
      title="Delete this goal?"
      description="This cannot be undone."
      cancelLabel="Keep goal"
      confirmLabel="Delete permanently"
      busyLabel="Deleting..."
      busy={false}
      icon={<span>icon</span>}
      onCancel={onCancel}
      onConfirm={onConfirm}
      {...overrides}
    />
  );

  return { onCancel, onConfirm };
}

describe("ConfirmationModal accessibility", () => {
  it("exposes the dialog's accessible name and description", () => {
    renderModal();

    const dialog = screen.getByRole("dialog", { name: "Delete this goal?" });
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.");
  });

  it("closes on Escape when not busy", () => {
    const { onCancel } = renderModal();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does not close on Escape while a confirm action is in progress", () => {
    const { onCancel } = renderModal({ busy: true });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("gives the backdrop close control an accessible name", () => {
    renderModal();

    expect(
      screen.getByRole("button", { name: "Close confirmation" })
    ).toBeInTheDocument();
  });
});
