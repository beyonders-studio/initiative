import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseHandle } from "@/hooks/useDirectMessages";
import { getErrorMessage } from "@/lib/errorMessage";

interface HandleFieldProps {
  label: string;
  placeholder: string;
  hint: string;
  submitLabel: string;
  /** Error key shown when the request fails without a code of its own. */
  errorFallback: string;
  pending: boolean;
  onSubmit: (handle: { username: string; discriminator: number }) => Promise<unknown>;
}

/** A `name#1234` field and its button: cleared on success, the reason on failure. */
export const HandleField = ({
  label,
  placeholder,
  hint,
  submitLabel,
  errorFallback,
  pending,
  onSubmit,
}: HandleFieldProps) => {
  const [handle, setHandle] = useState("");
  // An error belongs to the handle it was about, and shows only while the
  // field still holds it.
  const [failure, setFailure] = useState<{ handle: string; message: string } | null>(null);
  const error = failure?.handle === handle ? failure.message : null;
  const messageId = useId();

  const submit = () => {
    if (pending) return;
    const parsed = parseHandle(handle);
    if (!parsed) {
      setFailure({ handle, message: hint });
      return;
    }
    setFailure(null);
    onSubmit(parsed).then(
      // A handle typed while the request was out stays.
      () => setHandle((current) => (current === handle ? "" : current)),
      (err: unknown) => setFailure({ handle, message: getErrorMessage(err, errorFallback) })
    );
  };

  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <Input
          value={handle}
          onChange={(event) => setHandle(event.target.value)}
          placeholder={placeholder}
          aria-label={label}
          aria-describedby={messageId}
          aria-invalid={error ? true : undefined}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
        />
        <Button onClick={submit} disabled={pending || !handle.trim()}>
          {submitLabel}
        </Button>
      </div>
      <p
        id={messageId}
        aria-live="polite"
        className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}
      >
        {error ?? hint}
      </p>
    </div>
  );
};
