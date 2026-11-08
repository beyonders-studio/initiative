import { type AriaAttributes, createContext, type ReactNode, useContext, useId } from "react";

import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

type FieldControlProps = Pick<AriaAttributes, "aria-describedby" | "aria-invalid"> & {
  id?: string;
};

/**
 * What a `Field` hands the control inside it. The kit's fields read it, so a
 * control in a `Field` needs no id of its own. A popover's content sets it
 * back to nothing, so the inputs a field opens are not taken for the field.
 */
export const FieldContext = createContext<FieldControlProps | null>(null);

/**
 * The id, description and validity a control takes from the `Field` around
 * it. Its own id and validity win; its own description is read before the
 * field's.
 */
export function useFieldControl(own: FieldControlProps): FieldControlProps {
  const field = useContext(FieldContext);
  return {
    id: own.id ?? field?.id,
    "aria-describedby":
      [own["aria-describedby"], field?.["aria-describedby"]].filter(Boolean).join(" ") || undefined,
    "aria-invalid": own["aria-invalid"] ?? field?.["aria-invalid"],
  };
}

interface FieldProps {
  /** Names the control. */
  label: ReactNode;
  /** Muted text under the control, read with it. */
  hint?: ReactNode;
  /** Shown under the control while set, which also marks the control invalid. */
  error?: ReactNode;
  /** The control's id, for something else that names it; one is made otherwise. */
  id?: string;
  className?: string;
  /** One control. The kit's fields take their id, hint and error from here;
   *  another control reads them with `useFieldControl`. */
  children: ReactNode;
}

/**
 * A label, one control, and the hint and error under it. The label names the
 * control, and the hint and error describe it to a screen reader.
 */
export function Field({ label, hint, error, id, className, children }: FieldProps) {
  const madeId = useId();
  const controlId = id ?? madeId;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;

  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={controlId}>{label}</Label>
      <FieldContext
        value={{
          id: controlId,
          "aria-describedby": [hintId, errorId].filter(Boolean).join(" ") || undefined,
          "aria-invalid": error ? true : undefined,
        }}
      >
        {children}
      </FieldContext>
      {hint ? (
        <p id={hintId} className="text-muted-foreground text-xs">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </div>
  );
}
