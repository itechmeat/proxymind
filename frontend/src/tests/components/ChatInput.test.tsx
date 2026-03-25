import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "@/components/ChatInput";
import { strings } from "@/lib/strings";

describe("ChatInput", () => {
  it("sends on Enter and clears the input", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn().mockResolvedValue(undefined);

    render(<ChatInput onSend={onSend} status="ready" />);

    const input = screen.getByLabelText(strings.inputPlaceholder);
    await user.type(input, "Hello{Enter}");

    expect(onSend).toHaveBeenCalledWith("Hello");
    expect(input).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    render(<ChatInput onSend={onSend} status="ready" />);

    const input = screen.getByLabelText(strings.inputPlaceholder);
    await user.type(input, "Hello{Shift>}{Enter}{/Shift}World");

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("Hello\nWorld");
  });

  it("disables send for empty input", () => {
    render(<ChatInput onSend={vi.fn()} status="ready" />);

    expect(screen.getByRole("button", { name: strings.send })).toBeDisabled();
  });

  it("respects the disabled prop", () => {
    render(<ChatInput disabled onSend={vi.fn()} status="ready" />);

    expect(screen.getByLabelText(strings.inputPlaceholder)).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.send })).toBeDisabled();
  });

  it("disables controls while streaming", () => {
    render(<ChatInput onSend={vi.fn()} status="streaming" />);

    expect(screen.getByLabelText(strings.inputPlaceholder)).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.send })).toBeDisabled();
  });

  it("disables controls while submitted", () => {
    render(<ChatInput onSend={vi.fn()} status="submitted" />);

    expect(screen.getByLabelText(strings.inputPlaceholder)).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.send })).toBeDisabled();
  });

  it("keeps the draft when send fails", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn().mockRejectedValue(new Error("Failed to send"));

    render(<ChatInput onSend={onSend} status="ready" />);

    const input = screen.getByLabelText(strings.inputPlaceholder);
    await user.type(input, "Hello{Enter}");

    expect(onSend).toHaveBeenCalledWith("Hello");
    expect(input).toHaveValue("Hello");
  });

  it("does not send Enter while IME composition is active", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    render(<ChatInput onSend={onSend} status="ready" />);

    const input = screen.getByLabelText(strings.inputPlaceholder);
    await user.type(input, "你");

    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, {
      key: "Enter",
      code: "Enter",
    });

    expect(onSend).not.toHaveBeenCalled();

    fireEvent.compositionEnd(input);
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("你");
  });

  it("ignores rapid repeated submits while a send is in flight", async () => {
    const user = userEvent.setup();
    let resolveSend: (() => void) | undefined;
    const onSend = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveSend = resolve;
        }),
    );

    render(<ChatInput onSend={onSend} status="ready" />);

    const input = screen.getByLabelText(strings.inputPlaceholder);
    await user.type(input, "Hello");

    fireEvent.keyDown(input, {
      code: "Enter",
      key: "Enter",
    });
    fireEvent.keyDown(input, {
      code: "Enter",
      key: "Enter",
    });

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(input).toBeDisabled();

    resolveSend?.();

    await waitFor(() => {
      expect(input).toHaveValue("");
    });
  });
});
