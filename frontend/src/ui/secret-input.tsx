/**
 * A secret the server keeps and never sends back: a client secret, a key, a
 * password for a service.
 *
 * Once one is saved it reads as saved, with Replace beside it, rather than as
 * an empty box that looks like nothing was ever set. Replace opens the field
 * for a new one, and Keep the saved one closes it again. Whatever is typed is
 * the new secret; an empty field means the saved one stays, so a caller sends
 * nothing for it.
 */

import { Check } from "lucide-react";
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
  const focusNext = useRef(false);
  // What was last typed here. A value that empties without being typed away
  // was cleared by the caller (a save went through), so the saved one shows
  // again; one emptied by typing keeps the field open.
  const typed = useRef(value);

  useEffect(() => {
    if (value === "" && typed.current !== "") setReplacing(false);
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
          "flex min-h-9 items-center gap-2 rounded-md border border-input px-3 py-1 text-sm",
          className
        )}
      >
        <Check className="h-4 w-4 shrink-0 text-success" aria-hidden />
        <span className="font-medium">{t("secret.saved")}</span>
        {/* The field's label points here, so clicking it opens the field; the
            button is still called what it says. */}
        <Button
          {...control}
          aria-label={t("secret.replace")}
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto"
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
    <Input
      {...shared}
      ref={focusOnOpen}
      type="password"
      className={className}
      onChange={(event) => change(event.target.value)}
    />
  );

  if (!saved) return field;
  return (
    <div className="space-y-1">
      {field}
      <Button
        type="button"
        variant="link"
        size="sm"
        className="h-auto px-0"
        disabled={disabled}
        onClick={() => {
          change("");
          setReplacing(false);
        }}
      >
        {t("secret.keep")}
      </Button>
    </div>
  );
}
