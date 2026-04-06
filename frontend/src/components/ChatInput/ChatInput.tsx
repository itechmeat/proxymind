import type { ChatStatus } from "ai";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { strings } from "@/lib/strings";

import "./ChatInput.css";

interface ChatInputProps {
  disabled?: boolean;
  onSend: (text: string) => Promise<void> | void;
  status: ChatStatus;
}

export function ChatInput({
  disabled = false,
  onSend,
  status,
}: ChatInputProps) {
  const isComposingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [value, setValue] = useState("");
  const isDisabled =
    disabled ||
    isSubmitting ||
    status === "submitted" ||
    status === "streaming";
  const canSend = value.trim().length > 0 && !isDisabled;
  const wasDisabledRef = useRef(false);

  useEffect(() => {
    const wasDisabled = wasDisabledRef.current;
    wasDisabledRef.current = isDisabled;

    if (wasDisabled && !isDisabled) {
      textareaRef.current?.focus();
    }
  }, [isDisabled]);

  const resizeTextarea = () => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
  };

  const handleChange = (nextValue: string) => {
    setValue(nextValue);
    requestAnimationFrame(resizeTextarea);
  };

  const submit = async () => {
    const trimmed = value.trim();
    if (!trimmed || isDisabled) {
      return;
    }

    setIsSubmitting(true);
    try {
      await onSend(trimmed);
      setValue("");
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (textarea) {
          textarea.style.height = "";
        }
      });
    } catch {
      // Keep the current draft intact so the user can retry after a failed send.
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="chat-input__inner">
        <Textarea
          aria-label={strings.inputPlaceholder}
          className="chat-input__field"
          onCompositionEnd={() => {
            isComposingRef.current = false;
          }}
          onCompositionStart={() => {
            isComposingRef.current = true;
          }}
          disabled={isDisabled}
          onChange={(event) => handleChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !isComposingRef.current &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder={strings.inputPlaceholder}
          ref={textareaRef}
          rows={1}
          value={value}
        />
        <Button
          className="chat-input__button"
          disabled={!canSend}
          type="submit"
        >
          {strings.send}
        </Button>
      </div>
    </form>
  );
}
