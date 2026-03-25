import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ImageLightbox } from "@/components/ImageLightbox";

function ImageLightboxHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button onClick={() => setOpen(true)} type="button">
        Open lightbox
      </button>
      <ImageLightbox
        imageUrl="https://example.com/citation-image.png"
        onOpenChange={setOpen}
        open={open}
      />
    </>
  );
}

describe("ImageLightbox", () => {
  it("does not render the image before opening", () => {
    render(<ImageLightboxHarness />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("opens with the image when triggered", async () => {
    const user = userEvent.setup();

    render(<ImageLightboxHarness />);

    await user.click(screen.getByRole("button", { name: "Open lightbox" }));

    expect(
      screen.getByRole("img", { name: "Expanded citation image" }),
    ).toHaveAttribute("src", "https://example.com/citation-image.png");
  });

  it("closes via Escape key", async () => {
    const user = userEvent.setup();

    render(<ImageLightboxHarness />);

    await user.click(screen.getByRole("button", { name: "Open lightbox" }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("closes via overlay click", async () => {
    const user = userEvent.setup();

    render(<ImageLightboxHarness />);

    await user.click(screen.getByRole("button", { name: "Open lightbox" }));
    await user.click(screen.getByTestId("image-lightbox-overlay"));

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("closes via the close button", async () => {
    const user = userEvent.setup();

    render(<ImageLightboxHarness />);

    await user.click(screen.getByRole("button", { name: "Open lightbox" }));
    await user.click(
      screen.getByRole("button", { name: "Close image preview" }),
    );

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
