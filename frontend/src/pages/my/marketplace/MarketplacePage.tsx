import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { DecorationStore } from "@/pages/my/marketplace/DecorationStore";
import { HomeLayoutStore } from "@/pages/my/marketplace/HomeLayoutStore";
import { Button } from "@/ui/button";

/**
 * The marketplace a person gets things from for themselves.
 *
 * Separate from a community's, because the buyer is different and so is what
 * "installed" means: a community's install is shared by everyone in it, and
 * this one is yours and travels with you across every community you are in.
 * It sits outside the `/c/{id}` tree for the same reason.
 *
 * Two shelves: home layouts, which become views on your home page, and profile
 * packs, which dress your profile. It is a page rather than a section of
 * settings because getting something and configuring it are different acts,
 * and settings is where you configure.
 */
export const MarketplacePage = ({ user }: { user: UserRead }) => {
  const { t } = useTranslation(["marketplace", "profiles"]);

  return (
    <div className="space-y-10">
      <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>

      <HomeLayoutStore />

      <section className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h2 className="flex items-center gap-2 font-semibold text-xl">
              <Sparkles className="size-5 text-muted-foreground" aria-hidden="true" />
              {t("profiles:store.title")}
            </h2>
            <p className="text-muted-foreground text-sm">{t("profiles:store.description")}</p>
          </div>
          <Button variant="outline" asChild>
            <Link to="/profile">{t("profiles:store.manage")}</Link>
          </Button>
        </div>
        <DecorationStore user={user} />
      </section>
    </div>
  );
};
