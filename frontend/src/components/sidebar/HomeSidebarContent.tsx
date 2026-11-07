import { Link, useLocation } from "@tanstack/react-router";
import {
  CalendarDays,
  ChartColumn,
  House,
  LayoutGrid,
  LifeBuoy,
  MessageSquare,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { MessagesSidebarContent } from "@/components/sidebar/MessagesSidebarContent";
import { Badge } from "@/components/ui/badge";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useDirectMessagesEnabled } from "@/hooks/useDirectMessages";
import { useMessagesWaiting } from "@/hooks/useMyMessages";
import { useHasFiledTickets } from "@/hooks/useTickets";

export const HomeSidebarContent = () => {
  const { t } = useTranslation("nav");
  const pathname = useLocation({ select: (location) => location.pathname });

  // My Messages is a list of people and then one of them, so it drills rather
  // than sharing the column: opening it puts the conversations here and the
  // arrow in that header climbs back out to this list. Climbing out is a look
  // rather than a move -- the thread stays open beside it -- so it is state
  // here, and arriving at the route again drills back in.
  const onMessages = pathname.startsWith("/messages");
  const [climbedOut, setClimbedOut] = useState(false);
  useEffect(() => {
    setClimbedOut(false);
  }, [onMessages]);

  // Somebody asking to message you, or a message you have not read: the same
  // thing to whoever sees the mark, and counted in one place because the logo
  // above the rail draws it too.
  const messagesWaiting = useMessagesWaiting();

  // Whether this deployment offers messaging at all. Off, there is no item and
  // no route worth drilling into, so the whole branch below goes with it.
  const dmEnabled = useDirectMessagesEnabled();

  // Offered once the reader has filed something: before that it would be an
  // empty page in everybody's sidebar.
  const hasTickets = useHasFiledTickets();

  if (dmEnabled && onMessages && !climbedOut) {
    return <MessagesSidebarContent onBack={() => setClimbedOut(true)} />;
  }

  const navItems = [
    { to: "/", label: t("home"), icon: House, exact: true },
    { to: "/my-calendar", label: t("myCalendar"), icon: CalendarDays },
    { to: "/my-tools", label: t("myTools"), icon: LayoutGrid },
    ...(dmEnabled
      ? [
          {
            to: "/messages",
            label: t("myMessages"),
            icon: MessageSquare,
            // Encrypted messaging is new and moving: the badge is the one
            // place somebody is told before they rely on it.
            badge: t("alphaBadge"),
            waiting: messagesWaiting,
            // Climbing out of the conversations leaves this list showing
            // while the thread is still open behind it, so picking My Messages
            // again is not a navigation -- the address is already there and
            // nothing would re-run. It is a request to drill back in, and only
            // this says so.
            onSelect: () => setClimbedOut(false),
          },
        ]
      : []),
    ...(hasTickets ? [{ to: "/my-tickets", label: t("myTickets"), icon: LifeBuoy }] : []),
    { to: "/user-stats", label: t("myStats"), icon: ChartColumn },
  ];

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center justify-between gap-2 px-2.5">
          <h2 className="pride-wordmark min-w-0 flex-1 truncate font-semibold text-lg">
            initiative
          </h2>
        </div>
      </SidebarHeader>
      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const isActive = item.exact ? pathname === item.to : pathname.startsWith(item.to);
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={isActive}>
                      <Link
                        to={item.to}
                        className="flex items-center gap-2"
                        onClick={item.onSelect}
                      >
                        <item.icon className="h-4 w-4" />
                        <span>{item.label}</span>
                        {item.badge ? (
                          <Badge variant="secondary" className="h-4 shrink-0 px-1.5 text-3xs">
                            {item.badge}
                          </Badge>
                        ) : null}
                        {/* A dot carries no text, so the count it stands for
                            is written out for anyone not looking at it. */}
                        {item.waiting ? (
                          <span className="relative ms-auto flex shrink-0 items-center">
                            <span className="sr-only">
                              {t("requestsWaiting", { count: item.waiting })}
                            </span>
                            <span
                              aria-hidden="true"
                              className="size-2 rounded-full bg-destructive"
                            />
                          </span>
                        ) : null}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
