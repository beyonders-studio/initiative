import { Link } from "@tanstack/react-router";
import { Store } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolListingKind } from "@/lib/tools";
import { Button } from "@/ui/button";
import { DropdownMenuItem } from "@/ui/dropdown-menu";

type BrowseMarketplaceButtonProps = {
  /** Whose shelf to open. A tool with no listing kind renders nothing, so a
   *  list can offer the button unconditionally. */
  tool: Tool;
};

/**
 * "Browse the marketplace", beside the "create your first…" button of a tool
 * list that is still empty: adding a ready-made one is the same kind of answer
 * as making one from scratch. Once the list has something in it, the shelf is
 * an entry in the toolbar's More actions menu instead
 * ({@link BrowseMarketplaceMenuItem}).
 */
export const BrowseMarketplaceButton = ({ tool }: BrowseMarketplaceButtonProps) => {
  const { t } = useTranslation("marketplace");
  const gp = useCommunityPath();
  const kind = toolListingKind(tool);

  if (!kind) return null;

  const label = t("browse");
  return (
    <Button variant="outline" asChild>
      <Link to={gp("/marketplace")} search={{ kind }}>
        <Store className="h-4 w-4" />
        {label}
      </Link>
    </Button>
  );
};

/** "Browse the marketplace" as an entry in a toolbar's More actions menu.
 *  A tool with no listing kind renders nothing. */
export const BrowseMarketplaceMenuItem = ({ tool }: { tool: Tool }) => {
  const { t } = useTranslation("marketplace");
  const gp = useCommunityPath();
  const kind = toolListingKind(tool);
  if (!kind) return null;
  return (
    <DropdownMenuItem asChild>
      <Link to={gp("/marketplace")} search={{ kind }}>
        <Store className="h-4 w-4" />
        {t("browse")}
      </Link>
    </DropdownMenuItem>
  );
};
