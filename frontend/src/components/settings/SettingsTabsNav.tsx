import { useLocation, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { extractSubPath } from "@/lib/communityUrl";
import { Tabs, TabsBar, TabsTrigger } from "@/ui/tabs";

export interface SettingsTab {
  value: string;
  label: string;
  path: string;
  /** False leaves the tab out of the bar. */
  visible?: boolean;
  /** Optional mark after the label — a badge saying the tab needs a look. */
  adornment?: ReactNode;
}

export interface SettingsTabsNavProps {
  tabs: SettingsTab[];
  /**
   * Optional content rendered inside `<Tabs>` after the tab bar. Used by
   * layouts (e.g. user settings) that render their `<Outlet/>` within the tab
   * context; layouts that render the outlet outside `<Tabs>` omit this.
   */
  children?: ReactNode;
}

/** A path without its community prefix or trailing slashes. */
const tabPath = (path: string): string => extractSubPath(path).replace(/\/+$/, "") || "/";

/**
 * The tab bar of a settings area, whose tabs are routes. The tab lit is the
 * one with the longest path holding the address, matched without the
 * community prefix, or the first tab when none holds it; selecting a tab
 * navigates to its path.
 */
export function SettingsTabsNav({ tabs, children }: SettingsTabsNavProps) {
  const navigate = useNavigate();
  const pathname = useLocation({ select: (location) => tabPath(location.pathname) });
  const shown = tabs.filter((tab) => tab.visible !== false);
  const activeTab =
    shown
      .map((tab) => ({ value: tab.value, path: tabPath(tab.path) }))
      .sort((a, b) => b.path.length - a.path.length)
      .find(({ path }) => pathname === path || pathname.startsWith(`${path}/`))?.value ??
    shown[0]?.value ??
    "";

  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => {
        const tab = shown.find((item) => item.value === value);
        if (tab) {
          void navigate({ to: tab.path });
        }
      }}
    >
      <TabsBar containerClassName="pb-2" className="gap-1">
        {shown.map((tab) => (
          <TabsTrigger
            key={tab.value}
            value={tab.value}
            className={tab.adornment ? "gap-1.5" : undefined}
          >
            {tab.label}
            {tab.adornment}
          </TabsTrigger>
        ))}
      </TabsBar>
      {children}
    </Tabs>
  );
}
