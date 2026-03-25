import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { getInitials } from "@/lib/identity";
import { strings } from "@/lib/strings";

import "./ProfileEditModal.css";

interface ProfileEditModalProps {
  avatarUrl?: string;
  hasAvatar: boolean;
  name: string;
  onOpenChange: (open: boolean) => void;
  onRemoveAvatar: () => Promise<void> | void;
  onSave: (name: string) => Promise<void> | void;
  onUploadAvatar: (file: File) => Promise<void> | void;
  open: boolean;
}

export function ProfileEditModal({
  avatarUrl,
  hasAvatar,
  name,
  onOpenChange,
  onRemoveAvatar,
  onSave,
  onUploadAvatar,
  open,
}: ProfileEditModalProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const [draftName, setDraftName] = useState(name);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const effectiveAvatarUrl = previewUrl ?? avatarUrl;
  const showRemoveAvatar = Boolean(previewUrl) || hasAvatar;

  const readErrorMessage = (error: unknown, fallbackMessage: string) => {
    if (error instanceof Error && error.message.trim()) {
      return error.message;
    }

    return fallbackMessage;
  };

  const resetDraft = useEffectEvent(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setErrorMessage(null);
    setPreviewUrl(null);
    setDraftName(name);
  });

  useEffect(() => {
    if (open) {
      resetDraft();
    }
  }, [open]);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
      }
    };
  }, []);

  return (
    <Dialog.Root
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          resetDraft();
        }
        onOpenChange(nextOpen);
      }}
      open={open}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          className="profile-edit-modal__overlay"
          data-testid="profile-edit-modal-overlay"
        />
        <Dialog.Content className="profile-edit-modal__content">
          <div className="profile-edit-modal__header">
            <div>
              <Dialog.Title className="profile-edit-modal__title">
                {strings.profileTitle}
              </Dialog.Title>
              <Dialog.Description className="profile-edit-modal__description">
                {strings.profileDescription}
              </Dialog.Description>
            </div>

            <Dialog.Close asChild>
              <button
                aria-label={strings.profileClose}
                className="profile-edit-modal__close"
                type="button"
              >
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>

          <div className="profile-edit-modal__body">
            <div className="profile-edit-modal__avatar-row">
              <Avatar className="profile-edit-modal__avatar" size="lg">
                {effectiveAvatarUrl ? (
                  <img
                    alt={strings.profileAvatarAlt}
                    className="aspect-square size-full object-cover"
                    src={effectiveAvatarUrl}
                  />
                ) : null}
                {!effectiveAvatarUrl ? (
                  <AvatarFallback>
                    {getInitials(draftName || name)}
                  </AvatarFallback>
                ) : null}
              </Avatar>

              <button
                className="profile-edit-modal__avatar-trigger"
                onClick={() => {
                  fileInputRef.current?.click();
                }}
                type="button"
              >
                {strings.profileChangeAvatar}
              </button>

              <input
                accept="image/*"
                aria-label={strings.profileChangeAvatar}
                className="sr-only"
                onChange={async (event) => {
                  const input = event.currentTarget;
                  const file = input.files?.[0];
                  if (!file) {
                    return;
                  }

                  const previousPreviewUrl = previewUrlRef.current;
                  const nextPreviewUrl = URL.createObjectURL(file);
                  previewUrlRef.current = nextPreviewUrl;
                  setErrorMessage(null);
                  setPreviewUrl(nextPreviewUrl);
                  try {
                    await onUploadAvatar(file);
                    if (previousPreviewUrl) {
                      URL.revokeObjectURL(previousPreviewUrl);
                    }
                  } catch (error) {
                    URL.revokeObjectURL(nextPreviewUrl);
                    previewUrlRef.current = previousPreviewUrl;
                    setPreviewUrl(previousPreviewUrl);
                    setErrorMessage(
                      readErrorMessage(error, strings.profileUploadFailed),
                    );
                  } finally {
                    input.value = "";
                  }
                }}
                ref={fileInputRef}
                type="file"
              />
            </div>

            <div className="profile-edit-modal__field">
              <label
                className="profile-edit-modal__label"
                htmlFor="profile-name"
              >
                {strings.profileNameLabel}
              </label>
              <input
                className="profile-edit-modal__input"
                id="profile-name"
                onChange={(event) => {
                  setErrorMessage(null);
                  setDraftName(event.currentTarget.value);
                }}
                type="text"
                value={draftName}
              />
            </div>

            {errorMessage ? (
              <p className="profile-edit-modal__error" role="alert">
                {errorMessage}
              </p>
            ) : null}

            <div className="profile-edit-modal__actions">
              {showRemoveAvatar ? (
                <Button
                  onClick={async () => {
                    setErrorMessage(null);
                    try {
                      await onRemoveAvatar();
                      resetDraft();
                    } catch (error) {
                      setErrorMessage(
                        readErrorMessage(error, strings.profileRemoveFailed),
                      );
                    }
                  }}
                  type="button"
                  variant="outline"
                >
                  {strings.profileRemoveAvatar}
                </Button>
              ) : (
                <span />
              )}

              <div className="profile-edit-modal__actions-right">
                <Button
                  onClick={async () => {
                    setErrorMessage(null);
                    try {
                      await onSave(draftName);
                      resetDraft();
                      onOpenChange(false);
                    } catch (error) {
                      setErrorMessage(
                        readErrorMessage(error, strings.profileSaveFailed),
                      );
                    }
                  }}
                  type="button"
                >
                  {strings.profileSave}
                </Button>
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
