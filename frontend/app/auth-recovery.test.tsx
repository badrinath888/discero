import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ForgotPasswordPage from "./forgot-password/page";
import ResetPasswordPage from "./reset-password/page";
import VerifyEmailPage from "./verify-email/page";


const mocks = vi.hoisted(() => ({
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
  verifyEmail: vi.fn(),
  resendVerification: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: {
    children: ReactNode;
    href: string;
  }) => <a href={href} {...props}>{children}</a>,
}));

vi.mock("./lib/api", () => ({
  api: {
    forgotPassword: mocks.forgotPassword,
    resetPassword: mocks.resetPassword,
    verifyEmail: mocks.verifyEmail,
    resendVerification: mocks.resendVerification,
  },
  session: { clear: mocks.clearSession },
}));

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  mocks.forgotPassword.mockResolvedValue({ message: "Check your email." });
  mocks.resetPassword.mockResolvedValue({ message: "Password reset." });
  mocks.verifyEmail.mockResolvedValue({ message: "Email verified successfully." });
  mocks.resendVerification.mockResolvedValue({ message: "Verification sent." });
});

describe("authentication recovery flows", () => {
  it("submits a normalized forgot-password request", async () => {
    render(<ForgotPasswordPage />);

    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: " User@Example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByText("Check your email.")).toBeVisible();
    expect(mocks.forgotPassword).toHaveBeenCalledWith("user@example.com");
  });

  it("resets the password and clears the local session", async () => {
    window.history.replaceState({}, "", "/reset-password?token=reset-token");
    render(<ResetPasswordPage />);

    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "UpdatedPassword456!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "UpdatedPassword456!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByText("Password reset.")).toBeVisible();
    expect(mocks.resetPassword).toHaveBeenCalledWith(
      "reset-token",
      "UpdatedPassword456!"
    );
    expect(mocks.clearSession).toHaveBeenCalledOnce();
  });

  it("displays invalid or expired reset details from the backend", async () => {
    window.history.replaceState({}, "", "/reset-password?token=expired-token");
    mocks.resetPassword.mockRejectedValue(
      new Error("password reset link is invalid or expired (400 Bad Request)")
    );
    render(<ResetPasswordPage />);

    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "UpdatedPassword456!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "UpdatedPassword456!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "password reset link is invalid or expired (400 Bad Request)"
    );
  });

  it("verifies the token from the URL", async () => {
    window.history.replaceState({}, "", "/verify-email?token=verify-token");
    render(<VerifyEmailPage />);

    expect(await screen.findByText("Email verified successfully.")).toBeVisible();
    expect(mocks.verifyEmail).toHaveBeenCalledWith("verify-token");
  });

  it("resends verification and displays backend errors", async () => {
    mocks.resendVerification.mockRejectedValue(
      new Error("Email service unavailable (503 Service Unavailable)")
    );
    render(<VerifyEmailPage />);
    await waitFor(() => {
      expect(screen.getByText(/invalid or expired/i)).toBeVisible();
    });

    fireEvent.change(screen.getByLabelText("Need a new link?"), {
      target: { value: "User@Example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resend verification" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Email service unavailable (503 Service Unavailable)"
    );
    expect(mocks.resendVerification).toHaveBeenCalledWith("user@example.com");
  });
});
