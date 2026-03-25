import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatHeader } from "@/components/ChatHeader";
import { strings } from "@/lib/strings";

describe("ChatHeader", () => {
  it("renders the twin name", () => {
    render(<ChatHeader name="ProxyMind" />);

    expect(
      screen.getByRole("heading", { name: "ProxyMind" }),
    ).toBeInTheDocument();
  });

  it("renders the avatar image when a URL is provided", () => {
    render(
      <ChatHeader
        avatarUrl="https://example.com/avatar.png"
        name="ProxyMind"
      />,
    );

    expect(screen.getByRole("img", { name: "ProxyMind" })).toHaveAttribute(
      "src",
      "https://example.com/avatar.png",
    );
  });

  it("renders initials when no avatar URL is provided", () => {
    render(<ChatHeader name="Proxy Mind" />);

    expect(screen.getByText("PM")).toBeInTheDocument();
  });

  it("shows the settings button when admin mode is enabled", () => {
    render(<ChatHeader adminMode name="ProxyMind" />);

    expect(
      screen.getByRole("button", { name: strings.profileSettings }),
    ).toBeInTheDocument();
  });

  it("hides the settings button when admin mode is disabled", () => {
    render(<ChatHeader adminMode={false} name="ProxyMind" />);

    expect(
      screen.queryByRole("button", { name: strings.profileSettings }),
    ).not.toBeInTheDocument();
  });
});
