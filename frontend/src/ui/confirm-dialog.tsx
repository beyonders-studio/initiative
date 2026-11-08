import { type MouseEvent, type ReactNode, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/ui/alert-dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /**
   * The confirm button's click. The dialog closes after it unless the handler
   * calls `event.preventDefault()`, which keeps it open, for instance to show
   * an error beside the fields it asked for. Without one there is nothing to
   * confirm: the dialog only informs, and its cancel button is its one button.
   */
  onConfirm?: (event: MouseEvent<HTMLButtonElement>) => void;
  isLoading?: boolean;
  /** Text shown on the confirm button while ``isLoading``. */
  loadingLabel?: string;
  destructive?: boolean;
  /** Keeps the confirm button disabled while fields in ``children`` are not yet filled in. */
  confirmDisabled?: boolean;
  /**
   * When set, render a text input beneath the description and keep the
   * confirm button disabled until the typed value matches this string
   * exactly — the "type the name to confirm" guard.
   */
  confirmationText?: string;
  /** Label/prompt rendered above the confirmation input. */
  confirmationLabel?: ReactNode;
  /** Extra content rendered between the description and the confirmation input. */
  children?: ReactNode;
};

export const ConfirmDialog = ({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  isLoading,
  loadingLabel,
  destructive,
  confirmDisabled,
  confirmationText,
  confirmationLabel,
  children,
}: ConfirmDialogProps) => {
  const { t } = useTranslation("ui");
  const inputId = useId();
  const [confirmationInput, setConfirmationInput] = useState("");
  // What had focus when the dialog opened, usually the button that opened
  // it: focus goes back there when it closes.
  const opener = useRef<HTMLElement | null>(null);

  const requiresConfirmation = Boolean(confirmationText);

  // Reset the typed confirmation whenever the dialog closes, so a reopened
  // dialog starts blank, and when the expected phrase changes (e.g. a reused
  // dialog now guards a differently named resource).
  const [prev, setPrev] = useState({ open, confirmationText });
  if (prev.open !== open || prev.confirmationText !== confirmationText) {
    setPrev({ open, confirmationText });
    if (!open || prev.confirmationText !== confirmationText) setConfirmationInput("");
  }

  const confirmationSatisfied = !requiresConfirmation || confirmationInput === confirmationText;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        onOpenAutoFocus={() => {
          opener.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        }}
        onCloseAutoFocus={(event) => {
          if (!opener.current?.isConnected) return;
          event.preventDefault();
          opener.current.focus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && <AlertDialogDescription>{description}</AlertDialogDescription>}
        </AlertDialogHeader>
        {children}
        {requiresConfirmation && (
          <div className="space-y-2 py-2">
            {confirmationLabel && <Label htmlFor={inputId}>{confirmationLabel}</Label>}
            <Input
              id={inputId}
              value={confirmationInput}
              onChange={(e) => setConfirmationInput(e.target.value)}
              placeholder={confirmationText}
              autoComplete="off"
            />
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isLoading}>{cancelLabel ?? t("cancel")}</AlertDialogCancel>
          {onConfirm && (
            <AlertDialogAction
              onClick={onConfirm}
              disabled={isLoading || confirmDisabled || !confirmationSatisfied}
              variant={destructive ? "destructive" : "default"}
            >
              {isLoading
                ? (loadingLabel ?? t("confirm.working"))
                : (confirmLabel ?? t("confirm.continue"))}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
