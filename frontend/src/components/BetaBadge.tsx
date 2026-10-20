import { useTranslation } from "react-i18next";

import { badgeVariants } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Whether a version is from before 1.0.0, which is what the app calls beta. */
export const isBetaVersion = (version: string): boolean =>
  Number.parseInt(version.replace(/^v/, "").split(".")[0] ?? "", 10) < 1;

/**
 * "Beta", beside the app's mark, for as long as the app is before 1.0.0.
 * Nothing once it is not.
 */
export const BetaBadge = ({
  className,
  version = __APP_VERSION__,
}: {
  className?: string;
  version?: string;
}) => {
  const { t } = useTranslation("common");
  if (!isBetaVersion(version)) return null;
  return (
    <span
      className={cn(
        badgeVariants({ variant: "warning" }),
        "pointer-events-none uppercase tracking-wide",
        className
      )}
    >
      {t("beta")}
    </span>
  );
};
