/** The pieces every start step is built from. */

import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";

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
