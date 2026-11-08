import { Link } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  House,
  LogOut,
  MessageSquareHeart,
  Settings,
  ShieldCheck,
  UserCog,
} from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { AppLinks } from "@/components/AppLinks";
import { useTitleBarHeight } from "@/components/DesktopTitleBar";
import { ThoughtBubble } from "@/components/icons/ThoughtBubble";
import { AppearanceMenuItems, ThemeIcon } from "@/components/ModeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { SidebarFooter } from "@/components/sidebar/sidebar";
import { openFeedback, useFeedbackOffered } from "@/components/tickets/FeedbackSheet";
import { UserHandle } from "@/components/UserHandle";
import { PresenceDot } from "@/components/user/PresenceDot";
import { PresenceMenuItems } from "@/components/user/PresenceMenuItems";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { isStatusEmpty, StatusBubble, StatusEditor } from "@/components/user/ProfileStatus";
import { presenceLabelKey } from "@/lib/presence";
import { decorationSrc, resolveDecoration } from "@/lib/profileDecorations";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { Popover, PopoverAnchor, PopoverContent } from "@/ui/popover";

export interface SidebarUserFooterProps {
  /** The signed-in account, or null while it is still being fetched. */
  user: UserRead | null;
  canManagePlatformConfig: boolean;
  canAccessOperatorDashboard: boolean;
  onLogout: () => void;
  /** Re-read the account after the status or the presence is set from here. */
  refreshUser: () => Promise<void>;
}

export const SidebarUserFooter = ({
  user,
  canManagePlatformConfig,
  canAccessOperatorDashboard,
  onLogout,
  refreshUser,
}: SidebarUserFooterProps) => {
  const { t } = useTranslation(["nav", "profiles", "common"]);
  const feedbackOffered = useFeedbackOffered();
  // The desktop app's title bar carries the app's corner instead.
  const inTitleBar = useTitleBarHeight() > 0;
  // A fly-out needs a hover to open it and room beside the menu to land in.
  // A phone has neither — the sidebar is already a sheet against the edge — so
  // there the choices behind one are drilled into: the menu becomes that list,
  // and a back row climbs out again.
  const isMobile = !atLeast(useWidthClass(), "md");
  const [drill, setDrill] = useState<"presence" | "theme" | null>(null);
  const displayName = getUserDisplayName(user);
  const handle = getUrlHandle(user);
  const banner = resolveDecoration(user?.profile_decorations?.banner, "banner");
  const [statusOpen, setStatusOpen] = useState(false);
  // Asking for the editor only writes this down. It is opened once the menu has
  // gone (below), because the two are dismissable layers and a layer raised
  // while the one over it is still closing is a layer the closing one can take
  // down with it.
  const wantsStatus = useRef(false);
  const openStatusEditor = () => {
    wantsStatus.current = true;
  };

  return (
    <SidebarFooter className="border-t border-r">
      <div className="flex flex-col">
        {/* One line for the person: the picture, the name, and under it what
            they are up to. The status is a line rather than the bubble it is on
            a profile, because the sidebar is a strip and a bubble spends the
            height of a whole second row saying the same thing.

            The dot rides the picture here as it does everywhere else the person
            appears; it is no longer its own button, so setting it moved into
            the menu the row already opens, next to setting the status. */}
        <Popover open={statusOpen} onOpenChange={setStatusOpen}>
          <PopoverAnchor asChild>
            <div className="flex items-center gap-2 p-2">
              {/* modal={false}: a modal dropdown nested in the non-modal mobile
                  sidebar drawer dismisses the drawer on open. Matches the
                  notification-bell popover, which is non-modal and doesn't. */}
              {/* Every opening starts at the top of the menu, however deep it
                  was left — but only once it is closed, so nothing shifts
                  under the fingers on the way out. */}
              <DropdownMenu
                modal={false}
                onOpenChange={(open) => {
                  if (open) {
                    setDrill(null);
                    wantsStatus.current = false;
                  }
                }}
              >
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="h-auto min-w-0 flex-1 justify-start gap-2 px-2 py-1.5"
                  >
                    {/* Wearing the frame it is wearing on the profile: what you
                        picked is on you everywhere you appear, not only where
                        the picking happened. */}
                    <ProfileAvatar
                      user={user}
                      decorations={user?.profile_decorations}
                      presence={user?.presence}
                      className="size-8 text-xs"
                    />
                    <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden text-left">
                      <span className="w-full truncate font-medium text-sm leading-tight">
                        {displayName}
                      </span>
                      {user ? (
                        <span className="flex w-full min-w-0 items-center gap-1 pt-0.5 font-normal text-muted-foreground text-xs leading-tight">
                          {/* An emoji on its own is a status. The invitation is
                              for somebody who has said nothing at all — either
                              half standing alone is still something said. */}
                          {isStatusEmpty(user.custom_status) ? (
                            <span className="truncate">{t("profiles:status.empty")}</span>
                          ) : (
                            <>
                              {user.custom_status.emoji ? (
                                <span aria-hidden="true">{user.custom_status.emoji}</span>
                              ) : null}
                              {user.custom_status.text ? (
                                <span className="truncate">{user.custom_status.text}</span>
                              ) : null}
                            </>
                          )}
                        </span>
                      ) : null}
                    </div>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="w-72"
                  // The menu is gone by the time this runs, which is the moment
                  // the editor can have the screen to itself. The focus is not
                  // handed back to the row on the way, because the editor is
                  // about to take it.
                  onCloseAutoFocus={(event) => {
                    if (!wantsStatus.current) return;
                    wantsStatus.current = false;
                    event.preventDefault();
                    setStatusOpen(true);
                  }}
                >
                  {drill ? (
                    <>
                      <DropdownMenuItem
                        onSelect={(event) => {
                          event.preventDefault();
                          setDrill(null);
                        }}
                      >
                        <ChevronLeft className="h-4 w-4" /> {t("common:back")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      {drill === "presence" && user ? (
                        <>
                          <DropdownMenuLabel>{t("profiles:presence.edit")}</DropdownMenuLabel>
                          <PresenceMenuItems presence={user.presence} onChanged={refreshUser} />
                        </>
                      ) : (
                        <AppearanceMenuItems />
                      )}
                    </>
                  ) : (
                    <>
                      {user ? (
                        <>
                          {/* The menu opens onto the person rather than onto a
                          heading that says "My Account" — the banner, the
                          picture wearing whatever it wears, and the handle are
                          a better answer to "whose menu is this" than the
                          words are. The bubble comes back here, over the
                          banner where there is room for it, and is still the
                          way to change what it says. */}
                          <div className="relative -mx-1 -mt-1 mb-1 overflow-hidden rounded-t-md">
                            <div
                              className="h-16 w-full bg-center bg-cover bg-muted"
                              style={
                                banner
                                  ? {
                                      backgroundImage: `url(${decorationSrc(banner, user.profile_decorations?.grad_year)})`,
                                    }
                                  : undefined
                              }
                            />
                            {isStatusEmpty(user.custom_status) ? null : (
                              <DropdownMenuItem
                                className="absolute top-1.5 right-2 max-w-[70%] rounded-2xl p-0 focus:bg-transparent focus-visible:outline-2 focus-visible:outline-ring"
                                aria-label={t("profiles:status.edit")}
                                onSelect={openStatusEditor}
                              >
                                <StatusBubble status={user.custom_status} className="text-xs" />
                              </DropdownMenuItem>
                            )}
                            <div className="flex items-end gap-2 px-3 pb-2">
                              <ProfileAvatar
                                user={user}
                                decorations={user.profile_decorations}
                                presence={user.presence}
                                ring
                                className="-mt-6 size-14"
                              />
                              <div className="min-w-0 flex-1 pb-0.5">
                                <UserHandle
                                  user={user}
                                  className="max-w-full font-semibold text-sm"
                                  nameClassName="truncate"
                                />
                              </div>
                            </div>
                          </div>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onSelect={openStatusEditor}>
                            <ThoughtBubble className="h-4 w-4" /> {t("profiles:status.set")}
                          </DropdownMenuItem>
                          {/* Named by the answer rather than by the question: the
                          row is already showing which one you are on, so the
                          word that earns its place is "Online". */}
                          {isMobile ? (
                            <DropdownMenuItem
                              onSelect={(event) => {
                                event.preventDefault();
                                setDrill("presence");
                              }}
                            >
                              {/* Sized and boxed to the slot an icon takes on
                                  every other row, so the words start on one
                                  line down the menu. */}
                              <span className="flex size-4 shrink-0 items-center justify-center">
                                <PresenceDot presence={user.presence} className="size-3" />
                              </span>
                              {t(`profiles:${presenceLabelKey(user.presence)}`)}
                              <ChevronRight className="ml-auto h-4 w-4" />
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>
                                <span className="flex size-4 shrink-0 items-center justify-center">
                                  <PresenceDot presence={user.presence} className="size-3" />
                                </span>
                                {t(`profiles:${presenceLabelKey(user.presence)}`)}
                              </DropdownMenuSubTrigger>
                              <DropdownMenuPortal>
                                <DropdownMenuSubContent className="w-60">
                                  <PresenceMenuItems
                                    presence={user.presence}
                                    onChanged={refreshUser}
                                  />
                                </DropdownMenuSubContent>
                              </DropdownMenuPortal>
                            </DropdownMenuSub>
                          )}
                          <DropdownMenuSeparator />
                        </>
                      ) : (
                        <>
                          <DropdownMenuLabel>{t("myAccount")}</DropdownMenuLabel>
                          <DropdownMenuSeparator />
                        </>
                      )}
                      {handle ? (
                        <DropdownMenuItem asChild>
                          <Link to="/u/$handle" params={{ handle }}>
                            <CircleUserRound className="h-4 w-4" /> {t("myProfile")}
                          </Link>
                        </DropdownMenuItem>
                      ) : null}
                      <DropdownMenuItem asChild>
                        <Link to="/">
                          <House className="h-4 w-4" /> {t("home")}
                        </Link>
                      </DropdownMenuItem>
                      <DropdownMenuItem asChild>
                        <Link to="/profile">
                          <UserCog className="h-4 w-4" /> {t("mySettings")}
                        </Link>
                      </DropdownMenuItem>
                      {feedbackOffered ? (
                        <DropdownMenuItem onSelect={openFeedback}>
                          <MessageSquareHeart className="h-4 w-4" /> {t("sendFeedback")}
                        </DropdownMenuItem>
                      ) : null}
                      {isMobile ? (
                        <DropdownMenuItem
                          onSelect={(event) => {
                            event.preventDefault();
                            setDrill("theme");
                          }}
                        >
                          <ThemeIcon className="size-4" /> {t("theme")}
                          <ChevronRight className="ml-auto h-4 w-4" />
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuSub>
                          <DropdownMenuSubTrigger>
                            <ThemeIcon className="size-4" /> {t("theme")}
                          </DropdownMenuSubTrigger>
                          <DropdownMenuPortal>
                            <DropdownMenuSubContent className="w-40">
                              <AppearanceMenuItems />
                            </DropdownMenuSubContent>
                          </DropdownMenuPortal>
                        </DropdownMenuSub>
                      )}
                      {/* Running the place, kept apart from being in it: these
                          are somebody's other hat, not another thing about
                          their account. The rule only appears for the people
                          who have them. */}
                      {(canAccessOperatorDashboard || canManagePlatformConfig) && (
                        <>
                          <DropdownMenuSeparator />
                          {canAccessOperatorDashboard && (
                            <DropdownMenuItem asChild>
                              <Link to="/settings/operator">
                                <ShieldCheck className="h-4 w-4" /> {t("operatorDashboard")}
                              </Link>
                            </DropdownMenuItem>
                          )}
                          {canManagePlatformConfig && (
                            <DropdownMenuItem asChild>
                              <Link to="/settings/platform">
                                <Settings className="h-4 w-4" /> {t("platformSettings")}
                              </Link>
                            </DropdownMenuItem>
                          )}
                        </>
                      )}
                      <DropdownMenuSeparator />
                      {/* The one entry here that undoes rather than goes
                          somewhere, so it is coloured as the way out. */}
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onSelect={() => onLogout()}
                      >
                        <LogOut className="h-4 w-4" /> {t("signOut")}
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>

              {/* Only the bell rides out here: it is the one thing in this
                  corner worth a glance without opening anything. The theme
                  went into the menu — it is set once and left, and the width
                  it was holding is the width the status line reads in. */}
              {user ? (
                <div className="shrink-0">
                  <NotificationBell />
                </div>
              ) : null}
            </div>
          </PopoverAnchor>
          {user ? (
            <PopoverContent side="top" align="start" className="w-80 space-y-3">
              <StatusEditor
                status={user.custom_status}
                onSaved={refreshUser}
                onDone={() => setStatusOpen(false)}
              />
            </PopoverContent>
          ) : null}
        </Popover>
        {inTitleBar ? null : (
          <div className="flex justify-end border-t px-3 py-2">
            <AppLinks />
          </div>
        )}
      </div>
    </SidebarFooter>
  );
};
