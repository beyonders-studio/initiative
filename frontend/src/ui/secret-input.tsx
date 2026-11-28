/**
 * A secret the server keeps and never sends back: a client secret, a key, a
 * password for a service.
 *
 * A saved one is shown the way a vendor lists the credentials it issued: what
 * the server will say of it (a private key's fingerprint, or the last few
 * characters of anything else, as `hint`), marked saved, with Replace beside
 * it. Replace opens an empty field, and Cancel closes it again, keeping it.
 * Whatever is typed is the new secret; an empty field means the saved one
 * stays, so a caller sends nothing for it. A one-line secret can be shown
 * while it is typed.
 */

import { Check, Eye, EyeOff, KeyRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { useFieldControl } from "@/ui/field";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";

export interface SecretInputProps {
  /** Whether the server holds one. */
  saved: boolean;
  /** What the server shows of the saved one, when it shows anything. */
  hint?: string | null;
  /** What has been typed: the new secret, or empty to keep the saved one. */
  value: string;
  onValueChange: (value: string) => void;
  /** For a secret that spans lines, such as a PEM key. */
  multiline?: boolean;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

export function SecretInput({
  saved,
  hint,
  value,
  onValueChange,
  multiline = false,
  id,
  disabled,
  placeholder,
  className,
  ...aria
}: SecretInputProps) {
  const { t } = useTranslation("ui");
  const control = useFieldControl({ id, ...aria });
  const [replacing, setReplacing] = useState(false);
  const [shown, setShown] = useState(false);
  const focusNext = useRef(false);
  // What was last typed here. A value that empties without being typed away
  // was cleared by the caller (a save went through), so the saved one shows
  // again; one emptied by typing keeps the field open.
  const typed = useRef(value);

  useEffect(() => {
    if (value === "" && typed.current !== "") {
      setReplacing(false);
      setShown(false);
    }
    typed.current = value;
  }, [value]);

  const change = (next: string) => {
    typed.current = next;
    onValueChange(next);
  };

  if (saved && !replacing && value === "") {
    return (
      <div
        className={cn(
          "flex min-h-9 items-center gap-3 rounded-md border border-input px-3 py-1.5",
          className
        )}
      >
        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1 space-y-0.5">
          {hint && <p className="break-all font-mono text-xs">{hint}</p>}
          <p
            className={cn(
              "flex items-center gap-1",
              hint ? "text-muted-foreground text-xs" : "font-medium text-sm"
            )}
          >
            <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
            {t("secret.saved")}
          </p>
        </div>
        {/* The field's label points here, so clicking it opens the field; the
            button is still called what it says. */}
        <Button
          {...control}
          aria-label={t("secret.replace")}
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            focusNext.current = true;
            setReplacing(true);
          }}
        >
          {t("secret.replace")}
        </Button>
      </div>
    );
  }

  const focusOnOpen = (node: HTMLInputElement | HTMLTextAreaElement | null) => {
    if (node && focusNext.current) {
      focusNext.current = false;
      node.focus();
    }
  };
  const shared = {
    ...control,
    value,
    disabled,
    placeholder,
    autoComplete: "new-password",
    spellCheck: false,
  };
  const field = multiline ? (
    <Textarea
      {...shared}
      ref={focusOnOpen}
      rows={3}
      className={cn("font-mono text-xs", className)}
      onChange={(event) => change(event.target.value)}
    />
  ) : (
    <div className="relative">
      <Input
        {...shared}
        ref={focusOnOpen}
        type={shown ? "text" : "password"}
        className={cn("pr-10", className)}
        onChange={(event) => change(event.target.value)}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-1/2 right-0.5 -translate-y-1/2"
        aria-label={shown ? t("secret.hide") : t("secret.show")}
        aria-pressed={shown}
        disabled={disabled}
        onClick={() => setShown((now) => !now)}
      >
        {shown ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
      </Button>
    </div>
  );

  if (!saved) return field;
  // Replacing a saved one: Cancel keeps it.
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">{field}</div>
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        onClick={() => {
          change("");
          setReplacing(false);
          setShown(false);
        }}
      >
        {t("secret.cancel")}
      </Button>
    </div>
  );
}
