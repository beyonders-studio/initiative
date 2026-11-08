import { Signature } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

import { SignatureName } from "./PropertyValueCell";
import { signatureValue } from "./propertyHelpers";

interface SignatureFieldInputProps {
  /** The field's name, which the dialog names. */
  name: string;
  /** The signature as the server read it back, or the name just typed while
   *  it is saved, or the item it signs is being added. */
  value: unknown;
  /** Signs with the name typed. */
  onChange: (value: string) => void;
  /** When the item last changed, on its own page. */
  updatedAt?: string | null;
  disabled?: boolean;
}

/**
 * A signature field: who signed it and when, or a Sign button. Signing asks
 * for the signer's name under a statement of what signing does; the server
 * signs it as whoever sends it. Clearing it is the field's own.
 */
export const SignatureFieldInput = ({
  name,
  value,
  onChange,
  updatedAt,
  disabled = false,
}: SignatureFieldInputProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const inputId = useId();
  const signature = signatureValue(value);
  if (signature) return <SignatureName signature={signature} updatedAt={updatedAt} />;
  if (typeof value === "string" && value.trim()) {
    return <span className="text-sm">{t("input.signingAs", { name: value })}</span>;
  }
  const signed = typed.trim();
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={disabled}
      >
        <Signature className="h-4 w-4" aria-hidden />
        {t("input.sign")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form
            className="grid gap-4"
            // The dialog sits inside the field, whose Enter saves it and adds
            // an item being added; signing is this form's own.
            onKeyDown={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              if (!signed) return;
              // Out of the name field first, so the field takes the signature
              // as a pick rather than as typing.
              if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
              setOpen(false);
              setTyped("");
              onChange(signed);
            }}
          >
            <DialogHeader>
              <DialogTitle>{t("input.signTitle", { name })}</DialogTitle>
              <DialogDescription>{t("input.signStatement")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor={inputId}>{t("input.signNameLabel")}</Label>
              <Input
                id={inputId}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="name"
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                {t("common:cancel")}
              </Button>
              <Button type="submit" disabled={!signed}>
                {t("input.sign")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
};
