import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileEditModal } from "@/components/ProfileEditModal";
import { strings } from "@/lib/strings";

function ProfileEditModalHarness(props?: {
  avatarUrl?: string;
  hasAvatar?: boolean;
  open?: boolean;
}) {
  const [open, setOpen] = useState(props?.open ?? true);

  return (
    <>
      <button onClick={() => setOpen(true)} type="button">
        Reopen
      </button>
      <ProfileEditModal
        avatarUrl={props?.avatarUrl}
        hasAvatar={props?.hasAvatar ?? false}
        name="ProxyMind"
        onOpenChange={setOpen}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open={open}
      />
    </>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProfileEditModal", () => {
  it("does not render dialog content when closed", () => {
    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open={false}
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the current name in the input and saves changes", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => {});

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={onSave}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    const input = screen.getByLabelText(strings.profileNameLabel);
    await user.clear(input);
    await user.type(input, "Marcus Aurelius");
    await user.click(screen.getByRole("button", { name: strings.profileSave }));

    expect(onSave).toHaveBeenCalledWith("Marcus Aurelius");
  });

  it("closes through the close button", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={onOpenChange}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.click(
      screen.getByRole("button", { name: strings.profileClose }),
    );

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes through the Escape key", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={onOpenChange}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes through the overlay click", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={onOpenChange}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.click(screen.getByTestId("profile-edit-modal-overlay"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("creates a local preview and uploads the selected avatar file", async () => {
    const user = userEvent.setup();
    const onUploadAvatar = vi.fn(async () => {});
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:preview-avatar");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={onUploadAvatar}
        open
      />,
    );

    const file = new File(["avatar"], "avatar.png", { type: "image/png" });
    const input = screen.getByLabelText(strings.profileChangeAvatar);
    expect(input).toHaveAttribute("accept", "image/*");
    await user.upload(input, file);

    expect(createObjectURL).toHaveBeenCalledWith(file);
    expect(onUploadAvatar).toHaveBeenCalledWith(file);
    expect(
      screen.getByRole("img", { name: strings.profileAvatarAlt }),
    ).toHaveAttribute("src", "blob:preview-avatar");
  });

  it("restores the previous avatar preview when upload fails", async () => {
    const user = userEvent.setup();
    const onUploadAvatar = vi.fn(async () => {
      throw new Error("Upload failed");
    });
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:preview-avatar");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});

    render(
      <ProfileEditModal
        avatarUrl="https://example.com/avatar.png"
        hasAvatar
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={onUploadAvatar}
        open
      />,
    );

    const input = screen.getByLabelText(strings.profileChangeAvatar);
    const file = new File(["avatar"], "avatar.png", { type: "image/png" });
    await user.upload(input, file);

    expect(onUploadAvatar).toHaveBeenCalledWith(file);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-avatar");
    expect(
      screen.getByRole("img", { name: strings.profileAvatarAlt }),
    ).toHaveAttribute("src", "https://example.com/avatar.png");
    expect(screen.getByRole("alert")).toHaveTextContent("Upload failed");
    expect(createObjectURL).toHaveBeenCalledWith(file);
  });

  it("shows the remove avatar button only when an avatar exists", () => {
    const { rerender } = render(
      <ProfileEditModal
        avatarUrl="https://example.com/avatar.png"
        hasAvatar
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    expect(
      screen.getByRole("button", { name: strings.profileRemoveAvatar }),
    ).toBeInTheDocument();

    rerender(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    expect(
      screen.queryByRole("button", { name: strings.profileRemoveAvatar }),
    ).not.toBeInTheDocument();
  });

  it("calls the remove avatar handler", async () => {
    const user = userEvent.setup();
    const onRemoveAvatar = vi.fn(async () => {});

    render(
      <ProfileEditModal
        avatarUrl="https://example.com/avatar.png"
        hasAvatar
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={onRemoveAvatar}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.click(
      screen.getByRole("button", { name: strings.profileRemoveAvatar }),
    );

    expect(onRemoveAvatar).toHaveBeenCalled();
  });

  it("keeps the avatar visible and shows an error when removal fails", async () => {
    const user = userEvent.setup();
    const onRemoveAvatar = vi.fn(async () => {
      throw new Error("Remove failed");
    });

    render(
      <ProfileEditModal
        avatarUrl="https://example.com/avatar.png"
        hasAvatar
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={onRemoveAvatar}
        onSave={async () => {}}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.click(
      screen.getByRole("button", { name: strings.profileRemoveAvatar }),
    );

    expect(onRemoveAvatar).toHaveBeenCalled();
    expect(
      screen.getByRole("img", { name: strings.profileAvatarAlt }),
    ).toHaveAttribute("src", "https://example.com/avatar.png");
    expect(screen.getByRole("alert")).toHaveTextContent("Remove failed");
  });

  it("keeps the modal open and shows an error when save fails", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => {
      throw new Error("Save failed");
    });

    render(
      <ProfileEditModal
        hasAvatar={false}
        name="ProxyMind"
        onOpenChange={() => {}}
        onRemoveAvatar={async () => {}}
        onSave={onSave}
        onUploadAvatar={async () => {}}
        open
      />,
    );

    await user.click(screen.getByRole("button", { name: strings.profileSave }));

    expect(onSave).toHaveBeenCalledWith("ProxyMind");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Save failed");
  });

  it("discards unsaved name changes when closed without saving", async () => {
    const user = userEvent.setup();

    render(<ProfileEditModalHarness />);

    const input = screen.getByLabelText(strings.profileNameLabel);
    await user.clear(input);
    await user.type(input, "Unsaved name");
    await user.click(
      screen.getByRole("button", { name: strings.profileClose }),
    );
    await user.click(screen.getByRole("button", { name: "Reopen" }));

    expect(screen.getByLabelText(strings.profileNameLabel)).toHaveValue(
      "ProxyMind",
    );
  });
});
