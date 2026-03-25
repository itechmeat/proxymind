import { X } from "lucide-react";
import { Dialog } from "radix-ui";

import { strings } from "@/lib/strings";

import "./ImageLightbox.css";

interface ImageLightboxProps {
  imageUrl: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ImageLightbox({
  imageUrl,
  open,
  onOpenChange,
}: ImageLightboxProps) {
  if (!imageUrl) {
    return null;
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className="image-lightbox__overlay"
          data-testid="image-lightbox-overlay"
        />
        <Dialog.Content className="image-lightbox__content">
          <div className="image-lightbox__panel">
            <Dialog.Title className="sr-only">
              {strings.imageLightboxTitle}
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              {strings.imageLightboxDescription}
            </Dialog.Description>

            <Dialog.Close asChild>
              <button
                aria-label={strings.imageLightboxClose}
                className="image-lightbox__close"
                type="button"
              >
                <X size={18} />
              </button>
            </Dialog.Close>

            {open ? (
              <img
                alt={strings.imageLightboxImageAlt}
                className="image-lightbox__image"
                src={imageUrl}
              />
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
