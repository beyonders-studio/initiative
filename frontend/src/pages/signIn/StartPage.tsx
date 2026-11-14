import { Link, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { StartFlow } from "@/components/start/StartFlow";

/** Signing up: the start flow, ending in a new account. */
export const StartPage = () => {
  const { t } = useTranslation("auth");
  const { invite_code: inviteCode, next } = useSearch({ strict: false }) as {
    invite_code?: string;
    next?: string;
  };
  return (
    <StartFlow
      inviteCode={inviteCode?.trim() || undefined}
      next={next}
      footer={
        <p className="text-muted-foreground text-sm">
          {t("register.haveAccount")}{" "}
          <Link
            className="text-primary underline-offset-4 hover:underline"
            to="/login"
            search={next ? { next } : {}}
          >
            {t("register.signIn")}
          </Link>
        </p>
      }
    />
  );
};
