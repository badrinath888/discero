import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import AppSidebar from "./AppSidebar";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  clearSession: vi.fn(),
  pathname: "/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  usePathname: () => mocks.pathname,
}));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  const ignored = new Set(["initial", "animate", "exit", "transition"]);
  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    motion: new Proxy(
      {},
      {
        get:
          (_target, tag: string) =>
          ({ children, ...props }: Record<string, unknown>) =>
            createElement(
              tag,
              Object.fromEntries(
                Object.entries(props).filter(([name]) => !ignored.has(name))
              ),
              children as ReactNode
            ),
      }
    ),
    useReducedMotion: () => true,
  };
});

vi.mock("../lib/api", () => ({
  session: { clear: mocks.clearSession },
}));

describe("AppSidebar navigation", () => {
  it("renders each nav item as a real link with a href", () => {
    render(<AppSidebar />);

    const link = screen.getByRole("link", { name: "Transactions" });
    expect(link).toHaveAttribute("href", "/transactions");
  });

  it("marks the current page with aria-current", () => {
    render(<AppSidebar />);

    const active = screen.getByRole("link", { name: "Overview" });
    expect(active).toHaveAttribute("aria-current", "page");

    const inactive = screen.getByRole("link", { name: "Budgets" });
    expect(inactive).not.toHaveAttribute("aria-current");
  });

  it("exposes accessible names for the mobile menu controls", () => {
    render(<AppSidebar />);

    const openButton = screen.getByRole("button", {
      name: "Open navigation",
    });
    expect(openButton).toBeInTheDocument();

    fireEvent.click(openButton);

    expect(
      screen.getByRole("button", { name: "Close navigation" })
    ).toBeInTheDocument();
  });

  it("labels the navigation landmark", () => {
    render(<AppSidebar />);

    expect(
      screen.getByRole("navigation", { name: "Main navigation" })
    ).toBeInTheDocument();
  });
});
