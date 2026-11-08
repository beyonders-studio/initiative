/**
 * Who a plug-in comes from, said once before it first opens.
 *
 * Shown by the iPhone app the first time a member opens a community plug-in that
 * did not ship with Initiative: who publishes it, that the community and that
 * publisher provide it rather than Initiative, and a way to report it.
 * Continuing is remembered per server, member, community and plug-in
 * (`pluginNoticeKey`).
 */

import { useTranslation } from "react-i18next";

import type { CommunityPluginListingRef } from "@/api/generated/initiativeAPI.schemas";
import { ReportButton } from "@/components/moderation/ReportButton";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";

/** Where one member's acknowledgement for one plug-in in one community is kept. */
export const pluginNoticeKey = (
  server: string,
  userId: number,
  communityId: number,
  pluginId: number
) => `initiative-plugin-notice:${server}:${userId}:${communityId}:${pluginId}`;

export interface PluginProviderNoticeProps {
  name: string;
  listing: CommunityPluginListingRef | null;
  onContinue: () => void;
}

export function PluginProviderNotice({ name, listing, onContinue }: PluginProviderNoticeProps) {
  const { t } = useTranslation("plugins");

  return (
    <Card className="mx-auto mt-6 max-w-lg">
      <CardHeader>
        <CardTitle>{t("providerNotice.title", { name })}</CardTitle>
        {listing ? (
          <CardDescription>
            {t("providerNotice.madeBy", { name, publisher: listing.publisher })}
          </CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>{t("providerNotice.provided")}</p>
        {listing ? (
          <div className="flex items-center gap-1 text-muted-foreground">
            <span>{t("providerNotice.report")}</span>
            <ReportButton targetType="marketplace_listing" targetId={listing.id} />
          </div>
        ) : null}
      </CardContent>
      <CardFooter>
        <Button onClick={onContinue}>{t("providerNotice.continue")}</Button>
      </CardFooter>
    </Card>
  );
}
