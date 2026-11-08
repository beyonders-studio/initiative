import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { WikiPagesCard } from "@/components/initiativeTools/wikis/WikiPagesCard";
import { useRouteId } from "@/hooks/useRouteId";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings"
)({
  component: WikiSettings,
});

function WikiSettings() {
  const { t } = useTranslation("wikis");
  const wikiId = useRouteId("wikiId");
  return (
    <ToolSettingsPage
      tool={Tool.wiki}
      // Which page it opens on and what a new page copies: facts about this
      // wiki's contents, so they sit with its name and description.
      detailsExtra={wikiId !== null && <WikiPagesCard wikiId={wikiId} />}
      // How the wiki reads and what it looks like: more than a card holds, so
      // it gets its own section, served by the route beside the shared ones.
      extraTabs={[{ value: "reading", label: t("settings.tabReading") }]}
    />
  );
}
