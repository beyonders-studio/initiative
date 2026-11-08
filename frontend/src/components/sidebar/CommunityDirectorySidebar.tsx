/**
 * The community directory's filters, in the app's own sidebar.
 *
 * The directory is a place you browse rather than a page you read, so what
 * narrows it sits where everywhere else in the app keeps its navigation — the
 * sidebar — and the page beside it is nothing but the cards.
 *
 * Both filters live in the URL. This writes them and the page reads them, which
 * is how two components on opposite sides of the layout agree without a
 * provider strung between them, and it leaves a filtered directory linkable and
 * reload-proof besides.
 *
 * The shelves are links, so a category can be opened in a new tab like anything
 * else, and each carries the current search along rather than clearing it. The
 * search box is `CommunitySearchField`, which the page mounts instead on the
 * narrow screens where this sidebar is off-canvas.
 */

import { Link, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { CommunitySearchField } from "@/components/communities/CommunitySearchField";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/sidebar/sidebar";
import {
  asCommunityCategories,
  COMMUNITY_CATEGORIES,
  communityCategoryLabel,
} from "@/lib/communityCategories";

export const CommunityDirectorySidebar = () => {
  const { t } = useTranslation(["communities", "common"]);
  // Read loosely rather than through the route: this renders inside the app
  // shell, which is mounted above the route that declares these params.
  const search = useSearch({ strict: false }) as { category?: unknown };
  const categories = asCommunityCategories(search.category);

  // A shelf opens on itself alone, and shows as open while it is among the
  // ones picked; "All" is open when none are.
  const shelf = (value: (typeof COMMUNITY_CATEGORIES)[number] | undefined, label: string) => (
    <SidebarMenuItem key={value ?? "all"}>
      <SidebarMenuButton
        asChild
        isActive={value ? categories.includes(value) : categories.length === 0}
      >
        <Link
          to="/communities"
          search={(prev: Record<string, unknown>) => ({
            ...prev,
            category: value ? [value] : undefined,
          })}
        >
          <span className="truncate">{label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center gap-2 px-2.5">
          <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
            {t("communities:community.title")}
          </h2>
        </div>
      </SidebarHeader>
      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          <SidebarGroupContent>
            <CommunitySearchField />
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>{t("communities:community.categoriesHeading")}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {shelf(undefined, t("communities:community.allCategories"))}
              {COMMUNITY_CATEGORIES.map((value) => shelf(value, communityCategoryLabel(value, t)))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
