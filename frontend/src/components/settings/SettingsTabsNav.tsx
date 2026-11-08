import type { ReactNode } from "react";

import { Tabs, TabsBar, TabsTrigger } from "@/ui/tabs";

export interface SettingsTab {
  value: string;
  label: string;
  path: string;
  /** Optional mark after the label — a badge saying the tab needs a look. */
  adornment?: ReactNode;
}

export interface SettingsTabsNavProps {
  /** Tabs to render as triggers; also the pool `onNavigate` resolves against. */
  tabs: SettingsTab[];
  /** Value of the currently active tab. */
  activeTab: string;
  /** Called with the selected tab's `path` when the user switches tabs. */
  onNavigate: (path: string) => void;
  /**
   * Optional content rendered inside `<Tabs>` after the tab bar. Used by
   * layouts (e.g. user settings) that render their `<Outlet/>` within the tab
   * context; layouts that render the outlet outside `<Tabs>` omit this.
   */
  children?: ReactNode;
}

/**
 * Presentational tab bar shared by the settings and operator tabbed layouts: the
 * `<Tabs>` shell, a full-width `<TabsBar>`, and a `<TabsTrigger>` per tab.
 * Each layout keeps its own guards, header, and active-tab derivation.
 */
export function SettingsTabsNav({ tabs, activeTab, onNavigate, children }: SettingsTabsNavProps) {
  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => {
        const tab = tabs.find((item) => item.value === value);
        if (tab) {
          onNavigate(tab.path);
        }
      }}
    >
      <TabsBar containerClassName="pb-2" className="gap-1">
        {tabs.map((tab) => (
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
