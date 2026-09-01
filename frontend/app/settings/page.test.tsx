import {
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getAccounts: vi.fn(),
  searchTransactions: vi.fn(),
  changePassword: vi.fn(),
  changeEmail: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

const routerMock = { replace: mocks.replace, push: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("../components/AppSidebar", () => ({
  default: () => null,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getAccounts: mocks.getAccounts,
      searchTransactions: mocks.searchTransactions,
      changePassword: mocks.changePassword,
      changeEmail: mocks.changeEmail,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const user = {
  id: 1,
  email: "user@example.com",
  email_verified: true,
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue(user);
  mocks.getAccounts.mockResolvedValue([]);
  mocks.searchTransactions.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 1,
    total_pages: 0,
    total_income_cents: 0,
  });
});

describe("settings partial-data behavior", () => {
  it("still shows the profile when the secondary stats fetch fails", async () => {
    mocks.getAccounts.mockRejectedValue(new Error("stats down"));

    render(<SettingsPage />);

    expect(await screen.findByText("user@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.queryByText("stats down")).not.toBeInTheDocument();
  });
});

describe("settings stale toast handling", () => {
  it("clears a still-visible success message when a different form hits a validation error", async () => {
    mocks.changePassword.mockResolvedValue(undefined);
    render(<SettingsPage />);
    await screen.findByText("user@example.com");

    fireEvent.click(screen.getByRole("button", { name: "Change password" }));

    const passwordForm = screen
      .getByRole("button", { name: "Update password" })
      .closest("form") as HTMLFormElement;

    fireEvent.change(within(passwordForm).getByLabelText("Current password"), {
      target: { value: "OldPassword123!" },
    });
    fireEvent.change(within(passwordForm).getByLabelText("New password"), {
      target: { value: "NewPassword456!" },
    });
    fireEvent.change(
      within(passwordForm).getByLabelText("Confirm new password"),
      { target: { value: "NewPassword456!" } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Update password" })
    );

    expect(
      await screen.findByText("Password updated. Signing you out...")
    ).toBeInTheDocument();

    // Submitting the email form unchanged (but with its own required
    // password field filled) trips its own validation error, without
    // touching the password form above.
    fireEvent.click(screen.getByRole("button", { name: "Change email" }));

    const emailForm = screen
      .getByRole("button", { name: "Update email" })
      .closest("form") as HTMLFormElement;

    fireEvent.change(within(emailForm).getByLabelText("Current password"), {
      target: { value: "CurrentPassword123!" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Update email" })
    );

    expect(
      await screen.findByText("New email must be different.")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Password updated. Signing you out...")
    ).not.toBeInTheDocument();
  });
});
