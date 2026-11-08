import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { MentionComposer } from "@/components/markdown/MentionComposer";
import { usePastedImages } from "@/hooks/usePastedImages";
import { Button } from "@/ui/button";

interface CommentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (content: string) => void;
  placeholder?: string;
  submitLabel?: string;
  isSubmitting?: boolean;
  initiativeId: number;
  /** The thing being commented on, as a reference (`file:12`). A comment
   *  does not point at what it is a remark about — that is the page it is
   *  already on — so it is never offered. */
  subject?: string | null;
  error?: string | null;
  onClearError?: () => void;
  autoFocus?: boolean;
  compact?: boolean;
  /** When set, a Cancel button sits beside Submit and Escape dismisses. */
  onCancel?: () => void;
  cancelLabel?: string;
}

export const CommentInput = ({
  value,
  onChange,
  onSubmit,
  placeholder,
  submitLabel,
  isSubmitting = false,
  initiativeId,
  subject,
  error,
  onClearError,
  autoFocus = false,
  compact = false,
  onCancel,
  cancelLabel,
}: CommentInputProps) => {
  const { t } = useTranslation(["comments", "common"]);
  const resolvedPlaceholder = placeholder ?? t("placeholder");
  const resolvedSubmitLabel = submitLabel ?? t("postComment");
  const uploadImage = usePastedImages();

  // Handle form submit
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <MentionComposer
        value={value}
        onChange={(next) => {
          onChange(next);
          onClearError?.();
        }}
        initiativeId={initiativeId}
        subject={subject}
        onUploadImage={uploadImage}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            const trimmed = value.trim();
            if (trimmed && !isSubmitting) {
              onSubmit(trimmed);
            }
            return;
          }
          // The mention picker claims Escape first; a second press dismisses
          // the whole field.
          if (e.key === "Escape" && onCancel) {
            e.preventDefault();
            onCancel();
          }
        }}
        placeholder={resolvedPlaceholder}
        rows={compact ? 2 : 4}
        disabled={isSubmitting}
        autoFocus={autoFocus}
        compact={compact}
      />

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="flex items-center justify-end gap-2">
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            size={compact ? "sm" : "default"}
            onClick={onCancel}
            disabled={isSubmitting}
          >
            {cancelLabel ?? t("common:cancel")}
          </Button>
        )}
        <Button
          type="submit"
          disabled={isSubmitting || value.trim().length === 0}
          size={compact ? "sm" : "default"}
        >
          {isSubmitting ? t("posting") : resolvedSubmitLabel}
        </Button>
      </div>
    </form>
  );
};
