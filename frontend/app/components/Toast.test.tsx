import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Toast from "./Toast";

describe("Toast mobile layout", () => {
  it("allows long messages to wrap instead of overflowing narrow screens", () => {
    render(
      <Toast
        message="one or more transactions were not found (404 Not Found)"
        type="error"
        onClose={vi.fn()}
      />
    );

    const message = screen.getByText(
      "one or more transactions were not found (404 Not Found)"
    );

    expect(message.className).not.toContain("whitespace-nowrap");
  });

  it("keeps the notification width constrained to the viewport", () => {
    render(<Toast message="Saved." type="success" onClose={vi.fn()} />);

    const status = screen.getByRole("status");

    expect(status.className).toContain("max-w-[calc(100%-2rem)]");
  });
});
