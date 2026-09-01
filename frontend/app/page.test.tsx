import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  createUser: vi.fn(),
  getToken: vi.fn(),
  clear: vi.fn(),
  consumeNotice: vi.fn(),
  save: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("./lib/api", () => ({
  api: {
    getMe: mocks.getMe,
    login: mocks.login,
    createUser: mocks.createUser,
  },
  session: {
    getToken: mocks.getToken,
    consumeNotice: mocks.consumeNotice,
    clear: mocks.clear,
    save: mocks.save,
  },
}));

beforeEach(() => {
  mocks.getToken.mockReturnValue(null);
  mocks.consumeNotice.mockReturnValue("");
});

describe("landing page", () => {
  it("renders the hero headline and primary CTA", async () => {
    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: /discern before you decide/i })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Try Discero" }).length).toBeGreaterThan(0);
  });

  it("opens a focused sign-in panel that preserves the auth flow", async () => {
    render(<HomePage />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Sign in" }))[0]);

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/forgot-password");
  });

  it("keeps registration available and submits the create-account flow", async () => {
    mocks.createUser.mockResolvedValue({ id: 1, email: "new@example.com" });
    mocks.login.mockResolvedValue({ access_token: "token", user: { id: 1 } });
    render(<HomePage />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Try Discero" }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Create account" }));

    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Password123" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my account" }));

    await waitFor(() => expect(mocks.createUser).toHaveBeenCalledWith("new@example.com", "Password123"));
    expect(mocks.login).toHaveBeenCalledWith("new@example.com", "Password123");
  });

  it("closes the sign-in panel and returns to the landing experience", async () => {
    render(<HomePage />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Sign in" }))[0]);
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument()
    );
  });

  it("renders the key Decision Ripple content", async () => {
    render(<HomePage />);

    expect(await screen.findByText("Can I afford a $2,000 laptop?")).toBeInTheDocument();
    // "Affordable" and "94% confidence" now also appear in the hero's
    // illustrative HeroDecisionCard, so 2 legitimate occurrences are
    // expected in addition to the Decision Ripple section's own.
    expect(screen.getAllByText("Affordable").length).toBeGreaterThan(0);
    expect(screen.getAllByText("94% confidence").length).toBeGreaterThan(0);
    expect(screen.getByText("Protected")).toBeInTheDocument();
    expect(screen.getByText("Covered")).toBeInTheDocument();
  });

  it("renders without breaking when reduced motion is preferred", async () => {
    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: /discern before you decide/i })).toBeVisible();
    expect(screen.getAllByText("$32,475").length).toBeGreaterThan(0);
  });

  it("redirects to the dashboard when a valid session already exists", async () => {
    mocks.getToken.mockReturnValue("token");
    mocks.getMe.mockResolvedValue({ id: 1, email: "user@example.com" });
    render(<HomePage />);

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/dashboard"));
  });
});
