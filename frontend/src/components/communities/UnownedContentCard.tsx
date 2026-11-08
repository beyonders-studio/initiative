import { useTranslation } from "react-i18next";

import type { OwnedContentResponse, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useListUnownedContent } from "@/api/generated/users/users";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { toolCamelPlural } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

interface UnownedContentCardProps {
  onClaim: () => void;
}

/**
 * What no current member owns, and a way to put an admin back in charge.
 *
 * Leaving a community releases ownership rather than passing it on, so this is
 * where a departure's content lands. It also catches anything orphaned before
 * that — an owner grant naming someone who is no longer a member reads the same
 * way here, because in both cases nobody who can act on it owns it.
 */
export const UnownedContentCard = ({ onClaim }: UnownedContentCardProps) => {
  const { t } = useTranslation(["communities", "nav"]);
  const communityId = useActiveCommunityId();
  const { data } = useListUnownedContent(communityId);
  const content = data as unknown as OwnedContentResponse | undefined;
  const total = content?.total ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("unownedContent.title")}</CardTitle>
        <CardDescription>{t("unownedContent.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {total === 0 ? (
          <p className="text-muted-foreground text-sm">{t("unownedContent.empty")}</p>
        ) : (
          <>
            <p className="font-medium text-sm">{t("unownedContent.summary", { count: total })}</p>
            <ul className="space-y-1">
              {Object.entries(content?.counts ?? {}).map(([tool, count]) => (
                <li key={tool} className="text-muted-foreground text-sm">
                  {count} × {t(`nav:${toolCamelPlural(tool as Tool)}` as never)}
                </li>
              ))}
            </ul>
            <Button type="button" onClick={onClaim}>
              {t("unownedContent.claimButton")}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
};
