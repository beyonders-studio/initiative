import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { SEARCH_CATEGORIES, type SearchCategory } from "@/lib/searchResults";
import { TabsBar, TabsList, TabsTrigger } from "@/ui/tabs";

/** The palette's tabs: plain labels, the chosen one filled. */
const STRIP_TRIGGER =
  "px-2 font-normal text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-accent data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none";

interface SearchCategoryTabsProps {
  /** The tabs to offer, in the order given. Every one, unless a surface finds fewer kinds. */
  categories?: SearchCategory[];
  /**
   * `bar` is a page's tab bar. `strip` is a line of labels under an input, as
   * the command palette draws them, with `children` at its end.
   */
  variant?: "bar" | "strip";
  children?: ReactNode;
}

/**
 * The search tabs — Tools, Members, Comments, Tags — inside a `Tabs` whose
 * value is a {@link SearchCategory}.
 *
 * Members are read from the roster rather than the index (`categoryEntityTypes`
 * says so with `null`), so whatever sits under that tab asks the roster.
 *
 * Every tab stays open, including one holding nothing: closing it off leaves
 * the reader unable to confirm that for themselves, and unable to get back once
 * a changed query fills it. An empty tab says so.
 */
export const SearchCategoryTabs = ({
  categories = SEARCH_CATEGORIES,
  variant = "bar",
  children,
}: SearchCategoryTabsProps) => {
  const { t } = useTranslation("search");
  const strip = variant === "strip";
  const triggers = categories.map((category) => (
    <TabsTrigger key={category} value={category} className={strip ? STRIP_TRIGGER : undefined}>
      {t(`tabs.${category}`)}
    </TabsTrigger>
  ));

  return strip ? (
    <TabsList
      aria-label={t("title")}
      className="flex h-auto justify-start gap-1 rounded-none border-b bg-transparent px-2 py-1.5"
    >
      {triggers}
      {children}
    </TabsList>
  ) : (
    <TabsBar aria-label={t("title")}>{triggers}</TabsBar>
  );
};
