import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ConversationList } from "@/components/messages/ConversationList";
import { SidebarContent, SidebarGroup, SidebarHeader } from "@/components/sidebar/sidebar";
import { Button } from "@/components/ui/button";

/**
 * Who you are talking to, in the column the navigation was in.
 *
 * My Messages is a list of people and then one of them, which is two levels in
 * a place that has room for one. So opening it drills: the conversations take
 * the sidebar and the arrow in the header climbs back out.
 *
 * The list itself is `ConversationList`, which the page draws too — on a phone
 * this column is a sheet that shuts as soon as you pick anything, so it cannot
 * be the only place the list exists.
 */
export const MessagesSidebarContent = ({ onBack }: { onBack: () => void }) => {
  const { t } = useTranslation("messages");

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center gap-1 px-1.5">
          <Button variant="ghost" size="icon" className="size-8 shrink-0" onClick={onBack}>
            <ChevronLeft className="size-4" aria-hidden />
            <span className="sr-only">{t("backToNav")}</span>
          </Button>
          <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">{t("title")}</h2>
        </div>
      </SidebarHeader>

      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          <ConversationList />
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
