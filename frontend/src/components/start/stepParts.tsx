/** The pieces every start step is built from. */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Label } from "@/ui/label";

export const StepField = ({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) => (
  <div className="space-y-2">
    <Label htmlFor={id}>{label}</Label>
    {children}
    {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
  </div>
);

export const ContinueButton = ({
  onClick,
  disabled = false,
}: {
  onClick: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  return (
    <Button type="button" className="w-full" onClick={onClick} disabled={disabled}>
      {t("start.continue")}
    </Button>
  );
};

export const SkipButton = ({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) => {
  const { t } = useTranslation("auth");
  return (
    <Button type="button" variant="ghost" className="w-full" onClick={onClick} disabled={disabled}>
      {t("start.skip")}
    </Button>
  );
};
