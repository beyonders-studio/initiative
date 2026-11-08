import { useTranslation } from "react-i18next";

import { AdminSurface, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";

type ContactsViewProps = {
  /** The initiative this list belongs to. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's contacts: a table by name, as cards, or by tag. */
export const ContactsView = (props: ContactsViewProps) => (
  <ToolIndexPage tool={Tool.contact} {...props} />
);

/**
 * The /contacts route — the community contacts plug-in's own page.
 *
 * The community's own address book, in the same views as an initiative's. Its
 * contacts are added by whoever holds the community's contacts, once the
 * plug-in is there to hold them.
 */
export function CommunityContactsPage() {
  const { t } = useTranslation("contacts");
  const holds = useHeldSurfaces().holds(AdminSurface.community_contacts);
  const hasPlugin = Boolean(
    useCommunityPlugins().data?.items.some((plugin) => plugin.tool === Tool.contact)
  );

  return (
    <div className="space-y-6">
      <ToolPageHeader tool={Tool.contact} initiativeId={null} title={t("community.title")}>
        <p className="text-muted-foreground text-sm">{t("community.description")}</p>
      </ToolPageHeader>
      <ToolIndexPage tool={Tool.contact} fixedInitiativeId={null} canCreate={holds && hasPlugin} />
    </div>
  );
}
