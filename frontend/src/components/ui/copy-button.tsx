/**
 * Copy one value, and say whether it worked.
 *
 * A copy that quietly did not happen leaves somebody thinking they have the
 * thing, which is worse than no button: a callback URL they believe is on their
 * clipboard is a sign-in that fails later for a reason nobody can see. So the
 * clipboard is checked for before it is reached for, the rejected promise is
 * handled, and either way the button says what happened.
 */

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { host } from "@/ui/host";

/** Long enough to read the tick, short enough not to look stuck. */
const CONFIRM_MS = 2000;

export interface CopyButtonProps
  extends Omit<React.ComponentProps<typeof Button>, "onClick" | "children"> {
  value: string;
  /** Shown beside the icon. Omit for an icon-only button, which then carries
   *  the label as its accessible name instead. */
  label?: string;
  /** What the toast says on success. Defaults to a generic acknowledgement. */
  copiedMessage?: string;
}

export const CopyButton = ({
  value,
  label,
  copiedMessage,
  variant = "outline",
  size = "sm",
  ...props
}: CopyButtonProps) => {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  const copy = () => {
    if (!navigator?.clipboard) {
      host.toast.error(t("copyUnavailable"));
      return;
    }
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        host.toast.success(copiedMessage ?? t("copied"));
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), CONFIRM_MS);
      })
      .catch(() => host.toast.error(t("copyUnavailable")));
  };

  const Icon = copied ? Check : Copy;
  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      onClick={copy}
      aria-label={label ? undefined : t("copy")}
      {...props}
    >
      <Icon className="h-4 w-4" />
      {label}
    </Button>
  );
};
