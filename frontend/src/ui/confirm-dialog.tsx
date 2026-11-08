import { type ReactNode, useId, useState } from "react";

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
import { buttonVariants } from "@/ui/button";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  isLoading?: boolean;
  /** Text shown on the confirm button while ``isLoading``. */
  loadingLabel?: string;
  destructive?: boolean;
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
  confirmLabel = "Continue",
  cancelLabel = "Cancel",
  onConfirm,
  isLoading,
  loadingLabel = "Please wait...",
  destructive,
  confirmationText,
  confirmationLabel,
  children,
}: ConfirmDialogProps) => {
  const inputId = useId();
  const [confirmationInput, setConfirmationInput] = useState("");

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
      <AlertDialogContent>
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
          <AlertDialogCancel disabled={isLoading}>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isLoading || !confirmationSatisfied}
            className={cn(destructive && buttonVariants({ variant: "destructive" }))}
          >
            {isLoading ? loadingLabel : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
