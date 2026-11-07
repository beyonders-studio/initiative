import { useNavigate } from "@tanstack/react-router";
import { FilePlus, Home, Menu, MessageSquare, Plus, Search, SquareCheckBig } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getOpenCommandCenter } from "@/components/CommandCenter";
import { usePrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { useSidebar } from "@/components/sidebar/sidebar";
import { getOpenCreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { getOpenCreateToolWizard } from "@/components/tools/CreateToolWizard";
import { useAuth } from "@/hooks/useAuth";
import { useDirectMessagesEnabled } from "@/hooks/useDirectMessages";
import { useGlobalCreateAccess } from "@/hooks/useInitiativeAccess";
import { useMessagesWaiting } from "@/hooks/useMyMessages";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import { useNotifications } from "@/hooks/useNotifications";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";

const pillClass =
  "pointer-events-auto flex items-center gap-1 rounded-full border bg-card/90 p-1 shadow-lg backdrop-blur supports-backdrop-filter:bg-card/70";

/**
 * App-wide floating bottom navigation. The hamburger/search/home pill is mobile
 * only; the route-aware add pill renders at every viewport size and replaces the
 * old per-page `fixed right-6 bottom-6` floating add buttons.
 */
export function BottomNav() {
  const { t } = useTranslation("nav");
  const isMobile = !atLeast(useWidthClass(), "md");
  const navigate = useNavigate();
  const { setOpenMobile } = useSidebar();
  const { user } = useAuth();
  const { isCreateContext, action } = usePrimaryCreateAction();
  const globalCreate = useGlobalCreateAccess();

  // A connected tab is told when the inbox moves, so it polls only without a
  // channel — the rule the bell follows.
  const streamConnected = useNotificationStreamConnected();
  const notificationsQuery = useNotifications({
    refetchInterval: streamConnected ? false : 30_000,
    enabled: Boolean(user) && isMobile,
  });
  const unreadCount = notificationsQuery.data?.unread_count ?? 0;
  // The same count the sidebar item and the logo carry: a message nobody has
  // read, or somebody asking to send one.
  const messagesWaiting = useMessagesWaiting();
  // Both message buttons below are the same affordance at two sizes, so the
  // deployment's switch is read once for the pair.
  const dmEnabled = useDirectMessagesEnabled();
  // The count belongs in the name rather than beside it: a label wins over
  // what is inside the button, so a badge nobody can read is a number only
  // some people get. Both buttons below say it the same way.
  const messagesLabel =
    messagesWaiting > 0
      ? `${t("bottomNav.messages")}, ${t("requestsWaiting", { count: messagesWaiting })}`
      : t("bottomNav.messages");
  const waitingBadge =
    messagesWaiting > 0 ? (
      <Badge className="absolute -top-0.5 -right-0.5 h-5 min-w-5 justify-center rounded-full px-1 py-0 text-2xs">
        {messagesWaiting > 99 ? "99+" : messagesWaiting}
      </Badge>
    ) : null;

  // Hide the add button entirely on a create-context route where the user lacks
  // permission. Non-create routes (no registration) fall back to the global menu,
  // which itself hides when the user can create neither tasks nor files in
  // any of their communities.
  const canCreateGlobal = globalCreate.tool || globalCreate.task;
  const hideAdd = isCreateContext ? action === null : !canCreateGlobal;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40"
      style={{ paddingBottom: "var(--safe-area-inset-bottom)" }}
    >
      <div className="flex w-full items-end justify-center gap-3 px-4 pb-4 sm:px-6 sm:pb-6 md:justify-end">
        {isMobile && (
          <nav className={pillClass} aria-label={t("bottomNav.label")}>
            <Button
              variant="ghost"
              size="icon"
              className="relative h-11 w-11 rounded-full"
              onClick={() => setOpenMobile(true)}
              aria-label={t("bottomNav.menu")}
            >
              <Menu className="h-5 w-5" />
              {unreadCount > 0 ? (
                <Badge className="absolute -top-0.5 -right-0.5 h-5 min-w-5 justify-center rounded-full px-1 py-0 text-2xs">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </Badge>
              ) : null}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 rounded-full"
              onClick={() => void navigate({ to: "/" })}
              aria-label={t("bottomNav.home")}
            >
              <Home className="h-5 w-5" />
            </Button>
            {dmEnabled && (
              <Button
                variant="ghost"
                size="icon"
                className="relative h-11 w-11 rounded-full"
                onClick={() => void navigate({ to: "/messages" })}
                aria-label={messagesLabel}
              >
                <MessageSquare className="h-5 w-5" />
                {waitingBadge}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 rounded-full"
              onClick={() => getOpenCommandCenter()?.()}
              aria-label={t("bottomNav.search")}
            >
              <Search className="h-5 w-5" />
            </Button>
          </nav>
        )}

        {/* Beside the create button rather than inside the mobile pill, which
            is not drawn at this size: the two things somebody reaches for from
            anywhere are starting something and seeing who has written. The
            quieter of the two is on the left, so the primary action stays where
            it has always been. */}
        {!isMobile && dmEnabled && (
          <Button
            variant="secondary"
            size="icon"
            className="pointer-events-auto relative h-12 w-12 rounded-full shadow-lg"
            onClick={() => void navigate({ to: "/messages" })}
            aria-label={messagesLabel}
          >
            <MessageSquare className="h-5 w-5" />
            {waitingBadge}
          </Button>
        )}

        {!hideAdd &&
          (action ? (
            <Button
              size="icon"
              className="pointer-events-auto h-12 w-12 rounded-full shadow-lg shadow-primary/40 md:w-auto md:px-5"
              onClick={() => action.run()}
              aria-label={action.label || t("bottomNav.add")}
            >
              <Plus className="h-5 w-5" />
              <span className="hidden md:inline">{action.label}</span>
            </Button>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="icon"
                  className="pointer-events-auto h-12 w-12 rounded-full shadow-lg shadow-primary/40 md:w-auto md:px-5"
                  aria-label={t("bottomNav.add")}
                >
                  <Plus className="h-5 w-5" />
                  <span className="hidden md:inline">{t("bottomNav.add")}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="top" className="mb-2">
                {globalCreate.task && (
                  <DropdownMenuItem onSelect={() => getOpenCreateTaskWizard()?.()}>
                    <SquareCheckBig className="h-4 w-4" />
                    {t("bottomNav.addTask")}
                  </DropdownMenuItem>
                )}
                {globalCreate.tool && (
                  <DropdownMenuItem onSelect={() => getOpenCreateToolWizard(Tool.file)?.()}>
                    <FilePlus className="h-4 w-4" />
                    {t("bottomNav.addFile")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          ))}
      </div>
    </div>
  );
}
