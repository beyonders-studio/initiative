import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link, useRouter } from "@tanstack/react-router";
import { Check, ChevronsLeft, ChevronsRight, Clock, GripVertical, Lock, Plus } from "lucide-react";
import type { CSSProperties, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { Galaxy } from "@/components/icons/Galaxy";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSidebar } from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";
import { useMessagesWaiting } from "@/hooks/useMyMessages";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { communityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { getInitials } from "@/lib/initials";
import { toast } from "@/lib/mascotToast";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

import { BetaBadge } from "../BetaBadge";
import { LogoIcon } from "../LogoIcon";
import { CommunityCardFace } from "./CommunityCardFace";
import { CommunityContextMenu } from "./CommunityContextMenu";

// Swipe tuning — shared feel with the mobile drawer (see ui/sidebar.tsx).
const SWIPE_THRESHOLD = 60; // px to commit an open/close
const SWIPE_ENGAGE = 8; // px before a gesture counts as a horizontal drag
const FLYOUT_TRANSITION_MS = 300; // keep in sync with the inline transform transition
// Quick to start, long soft settle — the same curve for a tap and a released swipe.
const FLYOUT_EASING = "cubic-bezier(0.32, 0.72, 0, 1)";

const CreateCommunityButton = ({ expanded = false }: { expanded?: boolean }) => {
  const { createCommunity, canCreateCommunities, switchCommunity } = useCommunities();
  const { canSell, openPortal, reserveTab } = useBillingPortal();
  const { t } = useTranslation("communities");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  if (!canCreateCommunities) {
    return null;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    // Reserved inside the submit gesture (null when nothing may be sold here)
    // so the hop below isn't treated as an unsolicited popup.
    const billingTab = reserveTab();
    try {
      const newCommunity = await createCommunity({ name, description });
      await switchCommunity(newCommunity.id);
      setOpen(false);
      setName("");
      setDescription("");
      // Land in the community that was just made, with the new-initiative
      // wizard already open. It is empty, and naming its first initiative is
      // the next thing to do either way — so the wizard is the arrival rather
      // than something to go and find. `?create=true` is the same deep link the
      // sidebar and the empty state use, consumed once by the community home.
      await router.navigate({
        to: "/c/$communityId",
        params: { communityId: String(newCommunity.id) },
        search: { create: "true" },
      });
      if (canSell) {
        toast.info(t("billingSetup.opening", { community: newCommunity.name }));
        await openPortal(newCommunity.id, "upgrade", billingTab);
      }
    } catch (err) {
      billingTab?.close();
      console.error(err);
      const message = getErrorMessage(err, "communities:unableToCreateCommunity");
      setError(message);
      toast.error(message);
    } finally {
      // Deliberately no navigation here: a failed create keeps the dialog open
      // on its error, and leaving the page would throw that error away.
      setSubmitting(false);
    }
  };

  const trigger = expanded ? (
    <DialogTrigger asChild>
      <button
        type="button"
        className="flex w-full items-center gap-3 rounded-lg border border-muted-foreground/40 border-dashed px-3 py-2 text-left text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <Plus className="h-5 w-5" />
        </span>
        <span className="truncate font-medium text-sm">{t("createCommunity")}</span>
      </button>
    </DialogTrigger>
  ) : (
    <Tooltip>
      <TooltipTrigger asChild>
        <DialogTrigger asChild>
          <Button
            variant="secondary"
            size="icon"
            className="h-12 w-12 rounded-2xl border border-muted-foreground/40 border-dashed bg-transparent text-muted-foreground hover:bg-muted"
            aria-label={t("createCommunity")}
          >
            <Plus className="h-5 w-5" />
          </Button>
        </DialogTrigger>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={12}>
        <p>{t("createCommunity")}</p>
      </TooltipContent>
    </Tooltip>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !submitting && setOpen(next)}>
      {trigger}
      <DialogContent className="bg-card">
        <DialogHeader>
          <DialogTitle>{t("createCommunityTitle")}</DialogTitle>
          <DialogDescription>{t("createCommunityDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="community-name">{t("communityNameLabel")}</Label>
            <Input
              id="community-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("communityNamePlaceholder")}
              maxLength={255}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="community-description">{t("descriptionLabel")}</Label>
            <Textarea
              id="community-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={3}
            />
          </div>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? t("creating") : t("createCommunitySubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// Way in to the community directory, under "add a community": the other way to end
// up in a new community, for anyone without an invite to redeem. Shown wherever the
// directory runs, community creation on or off — a deployment that has switched
// creation off is exactly where joining an existing community is the only way in.
// Absent entirely where the platform owner runs no directory.
const JoinCommunityButton = ({
  expanded = false,
  onNavigate,
}: {
  expanded?: boolean;
  /** Closes the flyout on the way out, so the directory is not behind it. */
  onNavigate?: () => void;
}) => {
  const { t } = useTranslation("communities");
  const { communityDirectoryEnabled } = useAppConfig();
  const label = t("community.browse");

  if (!communityDirectoryEnabled) {
    return null;
  }

  if (expanded) {
    return (
      <Link
        to="/communities"
        onClick={onNavigate}
        className="flex w-full items-center gap-3 rounded-lg border border-muted-foreground/40 border-dashed px-3 py-2 text-left text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <Galaxy className="h-5 w-5" />
        </span>
        <span className="truncate font-medium text-sm">{label}</span>
      </Link>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="secondary"
          size="icon"
          className="h-12 w-12 rounded-2xl border border-muted-foreground/40 border-dashed bg-transparent text-muted-foreground hover:bg-muted"
          aria-label={label}
          asChild
        >
          <Link to="/communities" onClick={onNavigate}>
            <Galaxy className="h-5 w-5" />
          </Link>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={12}>
        <p>{label}</p>
      </TooltipContent>
    </Tooltip>
  );
};

export const CommunityAvatar = ({
  name,
  icon,
  active,
  size = "md",
  unread = false,
  closed = false,
}: {
  name: string;
  /** ``CommunityRead.icon_url`` — a path this server serves, not the bytes. */
  icon?: string | null;
  active: boolean;
  size?: "sm" | "md";
  /** Something in this community is unread. A dot, never a number. */
  unread?: boolean;
  /** Suspended: listed for its administrators, and closed to them. */
  closed?: boolean;
}) => {
  const initials = useMemo(() => getInitials(name, "G"), [name]);
  // Same-origin on web; on native it needs the API origin and a scoped token,
  // which is what an <img> can carry.
  const src = icon ? resolveHeaderlessApiUrl(icon) : null;
  return (
    <span className="relative block">
      <Avatar className={cn(size === "sm" ? "h-6 w-6" : "h-10 w-10", closed && "opacity-50")}>
        {src ? <AvatarImage src={src} alt={name} /> : null}
        <AvatarFallback
          className={cn(active && "bg-primary text-primary-foreground", size === "sm" && "text-xs")}
        >
          {initials}
        </AvatarFallback>
      </Avatar>
      {unread ? (
        // Where a presence badge sits, and ringed the same way: on the corner
        // of the round avatar rather than the square button behind it.
        <span
          aria-hidden="true"
          className={cn(
            "absolute right-0 bottom-0 rounded-full bg-primary ring-2 ring-background",
            size === "sm" ? "size-2" : "size-3"
          )}
        />
      ) : null}
      {closed ? (
        <span className="absolute -top-1 -right-1 rounded-full bg-background p-0.5">
          <Lock className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
        </span>
      ) : null}
    </span>
  );
};

const SortableCommunityButton = ({
  community,
  isActive,
  isHomeMode,
  onSelect,
  reorderMode,
  onStartReorder,
}: {
  community: CommunityRead;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (communityId: number) => void;
  reorderMode: boolean;
  /** Absent when there is nothing to reorder — a lone community has no order. */
  onStartReorder?: () => void;
}) => {
  const { t } = useTranslation("communities");
  // A dot, never a number: it says "something happened here", which is the
  // only question the rail is being asked.
  const unread = useUnreadTree();
  const hasUnread = unread.hasCommunity(community.id);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: community.id,
  });
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  if (isDragging) {
    style.opacity = 0.4;
  }
  return (
    <CommunityContextMenu community={community} onReorder={onStartReorder}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            ref={setNodeRef}
            // In reorder mode the tap belongs to the drag, not to switching.
            onClick={() => {
              if (!reorderMode) onSelect(community.id);
            }}
            className={cn(
              "relative flex h-12 w-12 cursor-grab items-center justify-center rounded-2xl border-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:cursor-grabbing",
              isActive
                ? isHomeMode
                  ? "border-transparent bg-muted text-foreground"
                  : "border-primary/60 bg-primary/10 text-primary"
                : "border-transparent bg-muted text-muted-foreground hover:bg-muted/80",
              reorderMode && "ring-2 ring-primary/50 ring-offset-2 ring-offset-sidebar"
            )}
            aria-label={
              reorderMode
                ? t("dragToReorder", { name: community.name })
                : t("switchTo", { name: community.name })
            }
            style={style}
            {...attributes}
            {...listeners}
          >
            {reorderMode ? (
              <span className="absolute -top-1 -right-1 z-10 rounded-full bg-background p-0.5 text-primary">
                <GripVertical className="h-3 w-3" aria-hidden="true" />
              </span>
            ) : null}
            {isActive && isHomeMode ? (
              <span
                className="absolute -bottom-2 left-1/2 z-10 mt-1 h-1 w-7 -translate-x-1/2 rounded-full bg-primary/60"
                aria-hidden="true"
              />
            ) : null}
            <CommunityAvatar
              name={community.name}
              icon={community.icon_url}
              active={isActive}
              unread={hasUnread}
              closed={!community.can.enter}
            />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={12}>
          {community.name}
          {hasUnread ? ` — ${t("unreadHere")}` : ""}
        </TooltipContent>
      </Tooltip>
    </CommunityContextMenu>
  );
};

const grantMinutesLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
};

// A non-draggable switcher button for a community reached via a temporary PAM
// grant. Visually distinct (dashed border + clock badge) and shows the
// remaining time on hover.
const GrantCommunityButton = ({
  community,
  isActive,
  onSelect,
}: {
  community: CommunityEntry;
  isActive: boolean;
  onSelect: (communityId: number) => void;
}) => {
  const { t } = useTranslation("communities");
  const left = grantMinutesLeft(community.grantExpiresAt);
  const unread = useUnreadTree();
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => onSelect(community.id)}
          className={cn(
            "relative flex h-12 w-12 items-center justify-center rounded-2xl border-3 border-dashed transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            isActive
              ? "border-primary/60 bg-primary/10 text-primary"
              : "border-muted-foreground/40 bg-muted text-muted-foreground hover:bg-muted/80"
          )}
          aria-label={t("switchTo", { name: community.name })}
        >
          <CommunityAvatar
            name={community.name}
            icon={community.icon_url}
            active={isActive}
            unread={unread.hasCommunity(community.id)}
          />
          <span className="absolute -top-1 -right-1 rounded-full bg-background p-0.5">
            <Clock className="h-3 w-3 text-amber-500" aria-hidden="true" />
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={12}>
        <p>{community.name}</p>
        {/* De-emphasize against the tooltip's own (primary) background — not
            text-muted-foreground, which is tuned for the card background and
            washes out on the colored tooltip. */}
        <p className="text-primary-foreground/80 text-xs">
          {t("temporaryAccess")}
          {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
        </p>
      </TooltipContent>
    </Tooltip>
  );
};

// Expanded ("Communities" flyout) card: the same face a community wears in the community
// directory. Member cards are drag-reorderable (via SortableCommunityRow) — with a
// mouse always, by touch only in reorder mode, which keeps press-and-hold free
// for the context menu and a horizontal swipe free to close the flyout. Grant
// cards pass no drag props.
const CommunityRow = ({
  community,
  isActive,
  isHomeMode,
  onSelect,
  innerRef,
  style,
  dragProps,
  reorderMode = false,
  onStartReorder,
  enterIndex,
}: {
  community: CommunityEntry;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (communityId: number) => void;
  innerRef?: (node: HTMLElement | null) => void;
  style?: CSSProperties;
  dragProps?: Record<string, unknown>;
  reorderMode?: boolean;
  onStartReorder?: () => void;
  /** Place in the list, for the staggered entrance. Absent: no entrance. */
  enterIndex?: number;
}) => {
  const { t } = useTranslation("communities");
  const isGrant = community.accessType === "grant";
  const left = isGrant ? grantMinutesLeft(community.grantExpiresAt) : null;
  const rowUnread = useUnreadTree();
  const highlighted = isActive && !isHomeMode;
  return (
    // The entrance sits on a wrapper, not the button, so it never contends
    // with the transform the drag sets on the button. `backwards` holds the
    // start frame through the delay and leaves nothing behind once it ends.
    <div
      className={cn(
        enterIndex !== undefined &&
          "motion-safe:fade-in-0 motion-safe:slide-in-from-left-4 motion-safe:animate-in motion-safe:fill-mode-backwards motion-safe:duration-300 motion-safe:ease-out"
      )}
      // The stagger stops growing after a few cards, so a long list arrives
      // together rather than trickling in.
      style={
        enterIndex !== undefined
          ? { animationDelay: `${60 + Math.min(enterIndex, 8) * 35}ms` }
          : undefined
      }
    >
      <CommunityContextMenu community={community} onReorder={onStartReorder}>
        <button
          type="button"
          ref={innerRef}
          style={style}
          // In reorder mode the tap belongs to the drag, not to switching.
          onClick={() => {
            if (!reorderMode) onSelect(community.id);
          }}
          className="group block w-full rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar"
          aria-label={
            reorderMode
              ? t("dragToReorder", { name: community.name })
              : t("switchTo", { name: community.name })
          }
          aria-current={isActive ? "true" : undefined}
          {...dragProps}
        >
          <CommunityCardFace
            // The whole card switches communities, so its location is a line
            // rather than a second control inside it.
            locationDetails={false}
            // The card rendition, as the directory shows it: this list is every
            // community the caller is in, and the full banner is many times heavier.
            community={{
              ...community,
              banner: { ...community.banner, image_url: community.banner_card_url },
            }}
            className={cn(
              "transition-[translate,scale,box-shadow,border-color] duration-200 ease-out group-hover:shadow-md motion-safe:group-active:scale-[0.98] motion-safe:group-hover:-translate-y-0.5",
              highlighted && "border-primary/60 ring-2 ring-primary/30",
              isGrant && !highlighted && "border-muted-foreground/40 border-dashed",
              reorderMode && "ring-2 ring-primary/40"
            )}
            avatar={
              <span className="relative shrink-0">
                <CommunityAvatar
                  name={community.name}
                  icon={community.icon_url}
                  active={isActive}
                  unread={rowUnread.hasCommunity(community.id)}
                  closed={!community.can.enter}
                />
                {isGrant ? (
                  <span className="absolute -top-1 -right-1 rounded-full bg-background p-0.5">
                    <Clock className="h-3 w-3 text-amber-500" aria-hidden="true" />
                  </span>
                ) : null}
              </span>
            }
            aside={
              reorderMode ? (
                <GripVertical className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              ) : null
            }
            meta={
              isGrant ? (
                <p className="mt-0.5 truncate text-muted-foreground text-xs">
                  {t("temporaryAccess")}
                  {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
                </p>
              ) : null
            }
          />
        </button>
      </CommunityContextMenu>
    </div>
  );
};

// Sortable wrapper for the flyout. Uses a `flyout-` id prefix so its draggable
// ids never collide with the collapsed rail's DndContext, which stays mounted.
const FLYOUT_DRAG_PREFIX = "flyout-";

const SortableCommunityRow = ({
  community,
  isActive,
  isHomeMode,
  onSelect,
  reorderMode,
  onStartReorder,
  enterIndex,
}: {
  community: CommunityEntry;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (communityId: number) => void;
  reorderMode: boolean;
  /** Absent when there is nothing to reorder — a lone community has no order. */
  onStartReorder?: () => void;
  enterIndex: number;
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `${FLYOUT_DRAG_PREFIX}${community.id}`,
  });
  return (
    <CommunityRow
      community={community}
      isActive={isActive}
      isHomeMode={isHomeMode}
      onSelect={onSelect}
      innerRef={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : undefined,
        cursor: "grab",
      }}
      dragProps={{ ...attributes, ...listeners }}
      reorderMode={reorderMode}
      onStartReorder={onStartReorder}
      enterIndex={enterIndex}
    />
  );
};

// Drag ids are numeric on the rail and `flyout-<id>` in the flyout; normalize.
const parseCommunityId = (id: string | number): number =>
  Number(String(id).replace(FLYOUT_DRAG_PREFIX, ""));

export const CommunitySidebar = ({ isHomeMode = false }: { isHomeMode?: boolean }) => {
  const {
    communities,
    activeCommunityId,
    switchCommunity,
    reorderCommunities,
    canCreateCommunities,
  } = useCommunities();
  const { suppressNextAutoClose, setSwipeCloseLocked } = useSidebar();
  const messagesWaiting = useMessagesWaiting();
  const { t } = useTranslation(["communities", "nav"]);
  const router = useRouter();
  const [activeDragId, setActiveDragId] = useState<number | null>(null);
  // Explicit reorder mode. Touch has no spare gesture: press-and-hold is the
  // context menu, and a horizontal swipe opens/closes the flyout — so touch
  // dragging is only wired up after the user picks "Reorder communities" (from the
  // context menu or the flyout header) and stays on until they tap Done.
  const [reorderMode, setReorderMode] = useState(false);
  const reorderModeRef = useRef(reorderMode);
  useEffect(() => {
    reorderModeRef.current = reorderMode;
  }, [reorderMode]);
  const startReorder = useCallback(() => setReorderMode(true), []);
  const stopReorder = useCallback(() => setReorderMode(false), []);

  // Mouse always reorders on a small drag; the touch sensor only joins the
  // context while reorder mode is on (useSensors drops the nulls).
  const mouseSensor = useSensor(MouseSensor, {
    activationConstraint: {
      distance: 6,
    },
  });
  const touchSensor = useSensor(TouchSensor, {
    activationConstraint: {
      distance: 8,
    },
  });
  const keyboardSensor = useSensor(KeyboardSensor, {
    coordinateGetter: sortableKeyboardCoordinates,
  });
  const sensors = useSensors(mouseSensor, reorderMode ? touchSensor : null, keyboardSensor);
  const draggedCommunity = useMemo(
    () => communities.find((community) => community.id === activeDragId) ?? null,
    [communities, activeDragId]
  );
  // Member communities are reorderable; grant (temporary) communities are rendered
  // separately below and are not sortable.
  const memberCommunities = useMemo(
    () => communities.filter((community) => community.accessType !== "grant"),
    [communities]
  );
  const grantCommunities = useMemo(
    () => communities.filter((community) => community.accessType === "grant"),
    [communities]
  );
  // A lone community has no order, so it is never offered one — and if the list
  // shrinks to one while reordering, the mode closes itself rather than
  // leaving taps inert.
  const canReorder = memberCommunities.length > 1;
  useEffect(() => {
    if (!canReorder) setReorderMode(false);
  }, [canReorder]);

  // --- Expandable "Communities" flyout state machine (mirrors MobileSidebar) ---
  // `expanded` is the desired state; `render`/`atOpen` decouple mount from the
  // resting position so the close transition can finish before unmount; `drag`
  // overrides position while a finger is down.
  const [expanded, setExpanded] = useState(false);
  const [render, setRender] = useState(false);
  const [atOpen, setAtOpen] = useState(false);
  const [drag, setDrag] = useState<{ base: "open" | "closed"; delta: number } | null>(null);
  const expandedRef = useRef(expanded);
  useEffect(() => {
    expandedRef.current = expanded;
  }, [expanded]);

  const collapse = useCallback(() => setExpanded(false), []);

  // Reorder mode owns horizontal gestures for its whole duration, not just
  // while a finger is down on a community — otherwise a missed grab would swipe
  // the drawer shut mid-reorder.
  useEffect(() => {
    if (!reorderMode) return;
    setSwipeCloseLocked(true);
    return () => setSwipeCloseLocked(false);
  }, [reorderMode, setSwipeCloseLocked]);

  useEffect(() => {
    if (expanded) {
      setRender(true);
      const id = requestAnimationFrame(() => setAtOpen(true));
      return () => cancelAnimationFrame(id);
    }
    setAtOpen(false);
    const id = window.setTimeout(() => setRender(false), FLYOUT_TRANSITION_MS);
    return () => clearTimeout(id);
  }, [expanded]);

  // True while a reorder drag is in progress. Touch drags only exist in reorder
  // mode (which already suspends the swipe gestures), so this mainly guards the
  // pen/stylus path from also engaging an open/close swipe.
  const dndActiveRef = useRef(false);

  // Swipe-to-open: a rightward swipe on the collapsed rail pulls the flyout in,
  // following the finger. Touch reorder is off unless reorder mode is on, so a
  // horizontal swipe never grabs a community icon. A leftward swipe is left to
  // bubble (it closes the mobile drawer); a vertical drag scrolls the rail.
  const openGesture = useRef({ x: 0, y: 0, active: false, engaged: false });
  const handleRailTouchStart = (e: React.TouchEvent) => {
    if (expandedRef.current || reorderModeRef.current) return;
    const touch = e.touches[0];
    openGesture.current = { x: touch.clientX, y: touch.clientY, active: true, engaged: false };
  };
  const handleRailTouchMove = (e: React.TouchEvent) => {
    // Check this first: a reorder drag cancels openGesture.active on its first
    // move, so this must run even after that early return would have fired. The
    // drawer's swipe-to-close is disabled separately via the sidebar's
    // swipe-close lock — not stopPropagation, which would also starve dnd-kit's
    // own document-level move listener.
    if (dndActiveRef.current || reorderModeRef.current) {
      openGesture.current.active = false;
      return;
    }
    const state = openGesture.current;
    if (!state.active) return;
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;
    if (!state.engaged) {
      if (Math.abs(dx) <= Math.abs(dy) || dx < 0) {
        state.active = false; // vertical scroll or leftward (drawer close)
        return;
      }
      if (dx < SWIPE_ENGAGE) return;
      state.engaged = true;
      setRender(true);
    }
    e.preventDefault();
    setDrag({ base: "closed", delta: dx });
  };
  const handleRailTouchEnd = (e: React.TouchEvent) => {
    const state = openGesture.current;
    if (!state.active) return;
    state.active = false;
    if (!state.engaged) return;
    const dx = e.changedTouches[0].clientX - state.x;
    setDrag(null);
    if (dx > SWIPE_THRESHOLD) {
      setAtOpen(true);
      setExpanded(true);
    } else {
      setAtOpen(false);
      window.setTimeout(() => {
        if (!expandedRef.current) setRender(false);
      }, FLYOUT_TRANSITION_MS);
    }
  };

  // Swipe-to-close: handlers on the flyout panel itself. stopPropagation keeps
  // a left-swipe here from bubbling up to the mobile drawer's swipe-to-close.
  const closeGesture = useRef({ x: 0, y: 0, active: false, engaged: false });
  const handlePanelTouchStart = (e: React.TouchEvent) => {
    e.stopPropagation();
    if (reorderModeRef.current) {
      closeGesture.current.active = false;
      return;
    }
    const touch = e.touches[0];
    closeGesture.current = { x: touch.clientX, y: touch.clientY, active: true, engaged: false };
  };
  const handlePanelTouchMove = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    e.stopPropagation();
    if (dndActiveRef.current) {
      state.active = false; // a reorder drag owns this gesture
      return;
    }
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;
    if (!state.engaged) {
      if (Math.abs(dx) <= Math.abs(dy)) return; // let the list scroll vertically
      if (dx > 0) {
        state.active = false; // rightward — not a close
        return;
      }
      if (Math.abs(dx) < SWIPE_ENGAGE) return;
      state.engaged = true;
    }
    e.preventDefault();
    setDrag({ base: "open", delta: dx });
  };
  const handlePanelTouchEnd = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    state.active = false;
    e.stopPropagation();
    if (!state.engaged) return;
    const dx = e.changedTouches[0].clientX - state.x;
    setDrag(null);
    if (dx < -SWIPE_THRESHOLD) {
      setAtOpen(false);
      setExpanded(false);
    }
    // Otherwise atOpen stays true and the panel animates back open.
  };

  const handleCommunitySwitch = (communityId: number) => {
    setExpanded(false);
    const community = communities.find((entry) => entry.id === communityId);
    if (communityId !== activeCommunityId) {
      // Switching communities navigates, but the sidebar should stay open (unlike
      // most navigations, which auto-close it on mobile).
      suppressNextAutoClose();
      void switchCommunity(communityId);
    }
    // A settings-only grant deliberately carries no content authority. Land
    // it on the section it can use instead of sending it through a denied
    // community-content request on the dashboard.
    const settingsOnly =
      community?.accessType === "grant" &&
      community.grantAccessLevel == null &&
      community.grantSettingsLevel != null;
    const destination = settingsOnly ? "/settings" : "/";
    router.navigate({ to: communityPath(communityId, destination) });
  };

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      dndActiveRef.current = true;
      // Suspend the mobile drawer's swipe-to-close while reordering so the two
      // gestures don't fight.
      setSwipeCloseLocked(true);
      const draggedId = parseCommunityId(event.active.id);
      if (Number.isFinite(draggedId)) {
        setActiveDragId(draggedId);
      }
    },
    [setSwipeCloseLocked]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      dndActiveRef.current = false;
      if (!reorderModeRef.current) setSwipeCloseLocked(false);
      const { active, over } = event;
      setActiveDragId(null);
      if (!over || active.id === over.id) {
        return;
      }
      const activeId = parseCommunityId(active.id);
      const overId = parseCommunityId(over.id);
      if (!Number.isFinite(activeId) || !Number.isFinite(overId)) {
        return;
      }
      const oldIndex = memberCommunities.findIndex((community) => community.id === activeId);
      const newIndex = memberCommunities.findIndex((community) => community.id === overId);
      if (oldIndex === -1 || newIndex === -1) {
        return;
      }
      const orderedIds = arrayMove(memberCommunities, oldIndex, newIndex).map(
        (community) => community.id
      );
      reorderCommunities(orderedIds);
    },
    [memberCommunities, reorderCommunities, setSwipeCloseLocked]
  );

  const handleDragCancel = useCallback(() => {
    dndActiveRef.current = false;
    if (!reorderModeRef.current) setSwipeCloseLocked(false);
    setActiveDragId(null);
  }, [setSwipeCloseLocked]);

  const panelTransform = drag
    ? `translateX(clamp(-100%, calc(${drag.base === "open" ? "0%" : "-100%"} + ${drag.delta}px), 0%))`
    : `translateX(${atOpen ? "0%" : "-100%"})`;

  return (
    <aside
      // z-30: the adjacent content column contains `relative` descendants
      // (SidebarGroup/SidebarMenuItem). Without a positive z-index here the
      // sticky rail (and its absolutely-positioned flyout) would paint beneath
      // those later-in-DOM siblings, bleeding the content through the flyout.
      className="sticky top-0 z-30 flex max-h-dvh w-20 flex-col items-center gap-3 border-r bg-sidebar px-2 pb-4"
      style={{ paddingTop: "calc(var(--safe-area-inset-top) + 1rem)" }}
      onTouchStart={handleRailTouchStart}
      onTouchMove={handleRailTouchMove}
      onTouchEnd={handleRailTouchEnd}
    >
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Link
              to="/"
              className={cn(
                "relative flex flex-col items-center rounded-2xl p-1 transition",
                isHomeMode && "bg-primary/10 ring-3 ring-primary/60"
              )}
              aria-label={t("nav:home")}
            >
              <LogoIcon className="h-10 w-10" aria-hidden="true" focusable="false" />
              <BetaBadge className="-mt-1 px-1.5 py-0 text-[0.625rem]" />
              {/* From inside a community this is the only thing pointing home,
                  so it carries the mark that something is waiting there. A dot
                  carries no text, so the count it stands for is written out for
                  anyone not looking at it. */}
              {messagesWaiting > 0 ? (
                <span className="absolute -top-0.5 -right-0.5 flex items-center">
                  <span className="sr-only">
                    {t("nav:requestsWaiting", { count: messagesWaiting })}
                  </span>
                  <span
                    aria-hidden="true"
                    className="size-2.5 rounded-full bg-destructive ring-2 ring-sidebar"
                  />
                </span>
              ) : null}
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={12}>
            <p>{t("nav:home")}</p>
          </TooltipContent>
        </Tooltip>
        <div className="scrollbar-thin flex min-h-0 flex-1 flex-col items-center gap-3 overflow-y-auto border-t py-3">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragCancel={handleDragCancel}
          >
            <SortableContext
              items={memberCommunities.map((community) => community.id)}
              strategy={verticalListSortingStrategy}
            >
              {memberCommunities.map((community) => (
                <SortableCommunityButton
                  key={community.id}
                  community={community}
                  isActive={community.id === activeCommunityId}
                  isHomeMode={isHomeMode}
                  onSelect={handleCommunitySwitch}
                  reorderMode={reorderMode}
                  onStartReorder={canReorder ? startReorder : undefined}
                />
              ))}
            </SortableContext>
            <DragOverlay>
              {draggedCommunity ? (
                <div className="pointer-events-none flex h-12 w-12 items-center justify-center rounded-2xl border-3 border-primary/60 bg-primary/20 opacity-80 shadow-lg">
                  <CommunityAvatar
                    name={draggedCommunity.name}
                    icon={draggedCommunity.icon_url}
                    active={draggedCommunity.id === activeCommunityId}
                  />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
          {grantCommunities.length > 0 ? (
            <div className="flex flex-col items-center gap-3 border-t pt-3">
              {grantCommunities.map((community) => (
                <GrantCommunityButton
                  key={community.id}
                  community={community}
                  isActive={community.id === activeCommunityId}
                  onSelect={handleCommunitySwitch}
                />
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-center gap-2 border-t pt-3">
          {reorderMode ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  onClick={stopReorder}
                  aria-label={t("communities:doneReordering")}
                >
                  <Check className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={12}>
                <p>{t("communities:doneReordering")}</p>
              </TooltipContent>
            </Tooltip>
          ) : null}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full text-muted-foreground hover:text-foreground"
                onClick={() => setExpanded(true)}
                aria-label={t("communities:expandCommunities")}
              >
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={12}>
              <p>{t("communities:communitiesHeading")}</p>
            </TooltipContent>
          </Tooltip>
          {canCreateCommunities ? <CreateCommunityButton /> : null}
          <JoinCommunityButton />
        </div>
      </TooltipProvider>

      {render ? (
        <>
          {/* Desktop click-away. On mobile the panel covers the whole drawer. */}
          <button
            type="button"
            className="fixed inset-0 z-30 hidden cursor-default md:block"
            onClick={collapse}
            aria-label={t("communities:collapseCommunities")}
            tabIndex={-1}
          />
          <div
            // Overlay the whole sidebar (rail + content column): stay anchored
            // at the rail's left edge and span the full sidebar width — on
            // mobile the drawer width, on desktop --sidebar-width.
            className="absolute top-0 left-0 z-40 flex h-dvh w-[var(--sidebar-width-mobile,90vw)] flex-col border-r bg-sidebar shadow-lg md:w-[var(--sidebar-width,20rem)]"
            style={{
              transform: panelTransform,
              transition: drag ? "none" : `transform ${FLYOUT_TRANSITION_MS}ms ${FLYOUT_EASING}`,
              paddingTop: "var(--safe-area-inset-top)",
            }}
            onTouchStart={handlePanelTouchStart}
            onTouchMove={handlePanelTouchMove}
            onTouchEnd={handlePanelTouchEnd}
          >
            <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
              <h2 className="font-semibold text-lg">{t("communities:communitiesHeading")}</h2>
              <div className="flex items-center gap-1">
                {canReorder ? (
                  <Button
                    variant={reorderMode ? "default" : "ghost"}
                    size="sm"
                    className="h-8 gap-1.5 px-2"
                    onClick={reorderMode ? stopReorder : startReorder}
                    aria-pressed={reorderMode}
                  >
                    {reorderMode ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <GripVertical className="h-4 w-4" />
                    )}
                    <span className="text-xs">
                      {reorderMode ? t("communities:doneReordering") : t("communities:reorder")}
                    </span>
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                  onClick={collapse}
                  aria-label={t("communities:collapseCommunities")}
                >
                  <ChevronsLeft className="h-4 w-4" />
                </Button>
              </div>
            </div>
            {reorderMode ? (
              <p className="shrink-0 border-b bg-muted/50 px-4 py-2 text-muted-foreground text-xs">
                {t("communities:reorderHint")}
              </p>
            ) : null}
            <div className="scrollbar-thin flex flex-1 flex-col gap-3 overflow-y-auto p-3">
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
                onDragCancel={handleDragCancel}
              >
                <SortableContext
                  items={memberCommunities.map(
                    (community) => `${FLYOUT_DRAG_PREFIX}${community.id}`
                  )}
                  strategy={verticalListSortingStrategy}
                >
                  {memberCommunities.map((community, index) => (
                    <SortableCommunityRow
                      key={community.id}
                      enterIndex={index}
                      community={community}
                      isActive={community.id === activeCommunityId}
                      isHomeMode={isHomeMode}
                      onSelect={handleCommunitySwitch}
                      reorderMode={reorderMode}
                      onStartReorder={canReorder ? startReorder : undefined}
                    />
                  ))}
                </SortableContext>
                <DragOverlay>
                  {draggedCommunity ? (
                    <CommunityRow
                      community={draggedCommunity}
                      isActive={draggedCommunity.id === activeCommunityId}
                      isHomeMode={isHomeMode}
                      onSelect={() => {}}
                      style={{ cursor: "grabbing" }}
                    />
                  ) : null}
                </DragOverlay>
              </DndContext>
              {grantCommunities.length > 0 ? (
                <div className="flex flex-col gap-3 border-t pt-3">
                  {grantCommunities.map((community, index) => (
                    <CommunityRow
                      key={community.id}
                      enterIndex={memberCommunities.length + index}
                      community={community}
                      isActive={community.id === activeCommunityId}
                      isHomeMode={isHomeMode}
                      onSelect={handleCommunitySwitch}
                    />
                  ))}
                </div>
              ) : null}
            </div>
            <div className="shrink-0 space-y-2 border-t p-2">
              {canCreateCommunities ? <CreateCommunityButton expanded /> : null}
              <JoinCommunityButton expanded onNavigate={collapse} />
            </div>
          </div>
        </>
      ) : null}
    </aside>
  );
};
