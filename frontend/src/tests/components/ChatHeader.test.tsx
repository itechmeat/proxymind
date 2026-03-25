import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { ChatHeader } from "@/components/ChatHeader";
import { strings } from "@/lib/strings";

function renderHeader(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("ChatHeader", () => {
  it("renders the twin name", () => {
    renderHeader(<ChatHeader name="ProxyMind" />);

    expect(
      screen.getByRole("heading", { name: "ProxyMind" }),
    ).toBeInTheDocument();
  });

  it("renders the avatar image when a URL is provided", () => {
    renderHeader(
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
    renderHeader(<ChatHeader name="Proxy Mind" />);

    expect(screen.getByText("PM")).toBeInTheDocument();
  });

  it("shows the settings button when admin mode is enabled", () => {
    renderHeader(<ChatHeader adminMode name="ProxyMind" />);

    expect(
      screen.getByRole("button", { name: strings.profileSettings }),
    ).toBeInTheDocument();
  });

  it("shows the admin link when admin mode is enabled", () => {
    renderHeader(<ChatHeader adminMode name="ProxyMind" />);

    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute(
      "href",
      "/admin",
    );
  });

  it("hides the settings button when admin mode is disabled", () => {
    renderHeader(<ChatHeader adminMode={false} name="ProxyMind" />);

    expect(
      screen.queryByRole("button", { name: strings.profileSettings }),
    ).not.toBeInTheDocument();
  });

  it("hides the admin link when admin mode is disabled", () => {
    renderHeader(<ChatHeader adminMode={false} name="ProxyMind" />);

    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  });
});
