import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { BetaBadge } from "@/components/BetaBadge";
import { LogoIcon } from "@/components/LogoIcon";
import { cn } from "@/lib/utils";

/**
 * The ground every signed-out card sits on: the hex backdrop and the
 * wordmark. Each card shows its server itself, as its last row.
 *
 * `fillPhone` drops the margin and the wordmark below `sm`, for a card that
 * takes the whole screen on a phone.
 */
export const SignInFrame = ({
  children,
  fillPhone = false,
}: {
  children?: ReactNode;
  fillPhone?: boolean;
}) => {
  const { t } = useTranslation("common");
  const isDark = document.documentElement.classList.contains("dark");

  return (
    <div
      style={{
        backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "67px 116px",
      }}
    >
      <div
        className={cn(
          "flex min-h-screen flex-col items-center justify-center gap-3 bg-muted/60 px-4 py-12",
          fillPhone && "max-sm:justify-start max-sm:p-0"
        )}
      >
        <div
          className={cn(
            "flex items-center gap-3 font-semibold text-3xl text-primary tracking-tight",
            fillPhone && "max-sm:hidden"
          )}
        >
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          <span className="pride-wordmark">{t("appName")}</span>
          <BetaBadge className="self-center" />
        </div>
        {children}
      </div>
    </div>
  );
};
