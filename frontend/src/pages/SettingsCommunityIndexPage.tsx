/**
 * What `/settings` shows when no tab is named: nothing of its own.
 *
 * The seat lands on Usage, its first tab; an ordinary admin, who cannot open
 * that one, lands on the first tab they can. Both read the tab bar's own list,
 * so nobody is sent to a page they would be refused, and a deep link to any
 * tab is untouched.
 */

import { Navigate } from "@tanstack/react-router";

import { useCommunitySettingsTabs } from "@/hooks/useCommunitySettingsTabs";

export function SettingsCommunityIndexPage() {
  const { tabs, isLoading } = useCommunitySettingsTabs();
  const [first] = tabs;
  return !isLoading && first ? <Navigate to={first.path} replace /> : null;
}
