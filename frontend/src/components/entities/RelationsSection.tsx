import {
  ChevronDown,
  ChevronUp,
  GalleryHorizontal,
  HelpCircle,
  LayoutGrid,
  type LucideIcon,
  Plus,
  Rows3,
  Waypoints,
} from "lucide-react";
import { lazy, type ReactNode, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type EndpointRef,
  type RelationshipRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { AddLinkDialog } from "@/components/entities/AddLinkDialog";
import { EntityCard } from "@/components/entities/EntityCard";
import { Button } from "@/components/ui/button";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DropOverlay } from "@/components/ui/file-drop";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useFileDrop } from "@/hooks/useFileDrop";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useRelatedStates } from "@/hooks/useRelatedStates";
import {
  type ToolRef,
  useRelationshipsFor,
  useRelationsNeighbourhood,
  useUnrelate,
} from "@/hooks/useRelationships";
import { docsUrl } from "@/lib/links";
import { toast } from "@/lib/mascotToast";
import {
  groupEdges,
  groupOf,
  RELATION_GROUP_ORDER,
  RELATION_GROUPS,
  type RelationGroup,
  type RelationGroupKey,
} from "@/lib/relationships";
import { getItem, setItem } from "@/lib/storage";
import { cn } from "@/lib/utils";

/**
 * The grid every group draws into. `min(…, 100%)` keeps a card from overflowing
 * a container narrower than one column.
 */
/**
 * Fetched when somebody asks for the picture, not before.
 *
 * The graph brings a rendering library and a layout worker with it — around
 * 200KB that a project, a task and a file page would otherwise all carry for
 * a view behind a menu that most readers never open.
 */
const RelationsGraph = lazy(() =>
  import("@/components/entities/RelationsGraph").then((module) => ({
    default: module.RelationsGraph,
  }))
);

const CARD_GRID =
  "grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(10rem,100%),1fr))]";

/** Rows stack in one column however wide the section is: a row is read across,
 *  so two of them side by side would be two lists to scan rather than one. */
const ROW_LIST = "flex flex-col";

/**
 * How a section draws what it found.
 *
 * `tiles` and `rows` keep a heading per kind of link. `carousel` and `graph`
 * deliberately do not: a carousel is one shelf you push along, and a graph is
 * one picture — so in both, what a link says is carried on the link itself.
 */
export type RelationsLayout = "tiles" | "rows" | "carousel" | "graph";

const LAYOUT_ICONS: Record<RelationsLayout, LucideIcon> = {
  tiles: LayoutGrid,
  rows: Rows3,
  // Not `GalleryHorizontalEnd`: that one is already the queue's own mark.
  carousel: GalleryHorizontal,
  graph: Waypoints,
};

const LAYOUTS: RelationsLayout[] = ["tiles", "rows", "carousel", "graph"];

const isLayout = (value: unknown): value is RelationsLayout =>
  typeof value === "string" && (LAYOUTS as string[]).includes(value);

interface RelationsSectionProps {
  /** The thing whose links these are. */
  entity: EndpointRef;
  /** Links made here stay inside one initiative, which the server enforces. */
  initiativeId: number | null;
  /**
   * The tool the anchor is addressed inside, so a write also refreshes the
   * tool's own copy of its side of the link. A project is its own tool; a task's
   * is its project.
   */
  anchorTool?: ToolRef | null;
  canEdit: boolean;
  /** Which headings this surface shows. Defaults to all of them. */
  groups?: RelationGroupKey[];
  /** Extra header buttons — a "New file" shortcut, say. */
  headerActions?: ReactNode;
  /** Persist the collapsed state and the chosen density under this key. */
  collapseKey?: string;
  /** How to draw these before anybody says otherwise: a shelf you push
   *  along, on every surface, until somebody picks another way. */
  defaultLayout?: RelationsLayout;
  /** What the thing itself is called, for the middle of the graph. */
  entityTitle?: string;
  title?: string;
  description?: string;
  className?: string;
}

/**
 * Everything connected to one thing, and the way to connect more.
 *
 * One request asks for every edge touching the thing, and the headings are
 * filters over that one answer — so adding a heading costs nothing. Which
 * heading an edge falls under, what it is called, and which way round asserting
 * one writes it all come from `@/lib/relationships`; this draws the result.
 *
 * A heading with nothing under it is not drawn. Seven empty headings would say
 * less than one line admitting there is nothing here yet.
 */
export const RelationsSection = ({
  entity,
  initiativeId,
  anchorTool,
  canEdit,
  groups = RELATION_GROUP_ORDER,
  headerActions,
  collapseKey,
  defaultLayout = "carousel",
  entityTitle,
  title,
  description,
  className,
}: RelationsSectionProps) => {
  const { t } = useTranslation("relations");
  const [collapsed, setCollapsed] = useState(
    () => Boolean(collapseKey) && getItem(collapseKey as string) === "true"
  );
  // Remembered per surface, like the collapsed state beside it: whoever chose a
  // way of looking at this probably wants it again next time.
  const layoutKey = collapseKey ? `${collapseKey}:layout` : null;
  const [layout, setLayout] = useState<RelationsLayout>(() => {
    const saved = layoutKey ? getItem(layoutKey) : null;
    return isLayout(saved) ? saved : defaultLayout;
  });
  const [adding, setAdding] = useState(false);
  /** A file dropped on the section, which the dialog opens already holding. */
  const [droppedFile, setDroppedFile] = useState<File | null>(null);
  const [hops, setHops] = useState(1);
  const [showTags, setShowTags] = useState(false);

  const shown = useMemo<RelationGroup[]>(() => groups.map((key) => RELATION_GROUPS[key]), [groups]);
  const assertable = useMemo(() => shown.filter((group) => group.assertable), [shown]);

  // Uploading makes a file in this initiative, so it is offered only to
  // somebody who has files there and may make one — and only where a link
  // may be made at all. Unknown until the initiative loads, which reads as no.
  const canAdd = canEdit && assertable.length > 0;
  const initiativesQuery = useInitiatives({ enabled: canAdd && initiativeId != null });
  const initiative = initiativesQuery.data?.find((item) => item.id === initiativeId);
  const canUpload =
    canAdd &&
    Boolean(initiative?.can.view.includes(Tool.file) && initiative.can.create.includes(Tool.file));

  const { data: rows = [], isLoading, isError } = useRelationshipsFor(entity);
  // Only walked while the picture is the thing on screen: no other layout shows
  // more than one hop, and one hop is the list above.
  const neighbourhood = useRelationsNeighbourhood(entity, hops, {
    enabled: layout === "graph" && !collapsed,
    includeTags: showTags,
  });
  const grouped = useMemo(() => groupEdges(rows, shown), [rows, shown]);

  const openDialog = (file: File | null = null) => {
    setDroppedFile(file);
    setAdding(true);
  };

  const closeDialog = () => {
    setAdding(false);
    setDroppedFile(null);
  };

  // The whole section takes a file, not just a box inside the dialog: a file
  // dragged in from the desktop lands wherever the cursor is. Off while the
  // dialog is up — it has a drop target of its own.
  const drop = useFileDrop(canUpload && !adding, (files) => {
    const [first] = files;
    if (first) openDialog(first);
  });

  const unrelate = useUnrelate(anchorTool, {
    onSuccess: () => toast.success(t("removed")),
  });

  const setLayoutState = (next: RelationsLayout) => {
    setLayout(next);
    if (layoutKey) setItem(layoutKey, next);
  };

  const setCollapsedState = (next: boolean) => {
    setCollapsed(next);
    if (collapseKey) setItem(collapseKey, next.toString());
  };

  /**
   * What is actually going to be drawn, not what came back.
   *
   * An edge no shown heading claims — a tag, on a surface that leaves tags to
   * the tag picker — is fetched and then not drawn, so counting the answer
   * would report "some" and then render an empty panel.
   */
  const visible = useMemo(() => rows.filter((row) => groupOf(row, shown) !== null), [rows, shown]);
  const total = visible.length;

  // What each far end is doing now, in one batched request for the whole panel.
  // Not asked for while the graph is up: that view draws names, not readings.
  const states = useRelatedStates(visible, !collapsed && layout !== "graph");

  /**
   * How many of a group's links are still outstanding, where that means
   * anything.
   *
   * Only shown for the groups where it changes what a reader does. "3" under
   * Blocked by is a worry; "1 of 3 still open" is the actual answer, and a
   * heading that keeps saying 3 after everything is done is why nobody trusted
   * the panel. A group whose ends never finish counts nothing and says nothing.
   */
  const openTally = (edges: RelationshipRead[]) => {
    const answerable = edges.filter((edge) => edge.other.is_open !== null);
    if (answerable.length === 0) return null;
    return {
      open: answerable.filter((edge) => edge.other.is_open).length,
      total: answerable.length,
    };
  };

  // One name on every surface. The empty line is contextual, from the thing
  // itself, so no caller has to pass copy for a surface it happens to sit on;
  // i18next falls back to the bare key for a kind with no wording of its own.
  const sectionTitle = title ?? t("title");
  const emptyLine = t("empty", { context: entity.type });

  return (
    <Collapsible
      open={!collapsed}
      onOpenChange={(open) => setCollapsedState(!open)}
      className={cn("relative space-y-3", className)}
      {...drop.handlers}
    >
      {drop.dragging ? <DropOverlay label={t("dropzone")} className="rounded-2xl" /> : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-2">
            <Waypoints className="h-5 w-5 text-muted-foreground" />
            <h2 className="font-semibold text-xl tracking-tight">{sectionTitle}</h2>
            {total > 0 ? <span className="text-muted-foreground text-sm">{total}</span> : null}
            {/* The explanation lives one hover away rather than under the
                heading forever: it is onboarding copy, and onboarding copy that
                never leaves is just noise on the surface somebody already
                understands. */}
            <HoverCard>
              <HoverCardTrigger asChild>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t("help.title")}
                >
                  <HelpCircle className="h-4 w-4" />
                </button>
              </HoverCardTrigger>
              <HoverCardContent side="left" align="start" className="w-72">
                <p className="font-medium text-sm">{t("help.title")}</p>
                <p className="mt-2 text-muted-foreground text-sm">
                  {description ?? t("help.body")}
                </p>
                <p className="mt-2 text-muted-foreground text-sm">{t("help.derived")}</p>
                <a
                  href={docsUrl("guides/mentions-and-links/#relations")}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-block font-medium text-sm underline underline-offset-4"
                >
                  {t("help.learnMore")}
                </a>
              </HoverCardContent>
            </HoverCard>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-full"
              onClick={() => setCollapsedState(!collapsed)}
              aria-expanded={!collapsed}
              aria-label={sectionTitle}
            >
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Four ways of looking at nothing is four ways of looking at
              nothing. The switcher arrives with the first link. */}
          {total > 0 ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label={t("layout.label")}
                  title={t("layout.label")}
                >
                  {(() => {
                    const Icon = LAYOUT_ICONS[layout];
                    return <Icon className="h-4 w-4" />;
                  })()}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {LAYOUTS.map((option) => {
                  const Icon = LAYOUT_ICONS[option];
                  return (
                    <DropdownMenuItem
                      key={option}
                      onSelect={() => setLayoutState(option)}
                      className={option === layout ? "bg-accent" : undefined}
                    >
                      <Icon className="h-4 w-4" />
                      {t(`layout.${option}`)}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          {headerActions}
          {canAdd ? (
            <Button type="button" size="sm" variant="outline" onClick={() => openDialog()}>
              <Plus className="h-4 w-4" />
              {t("add")}
            </Button>
          ) : null}
        </div>
      </div>

      <CollapsibleContent className="space-y-6 data-[state=closed]:hidden">
        {isLoading ? (
          <div className={layout === "rows" ? ROW_LIST : CARD_GRID}>
            {[0, 1, 2, 3].map((n) => (
              <Skeleton
                key={n}
                className={
                  layout === "rows" ? "h-12 rounded-lg" : "aspect-4/3 rounded-2xl sm:aspect-square"
                }
              />
            ))}
          </div>
        ) : isError ? (
          <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>
        ) : total === 0 ? (
          /* One line, naming two things worth linking from HERE. Not a button
             per kind of link: that would be seven doors into a room nobody has
             been told the purpose of, and the one door already exists. */
          <p className="text-muted-foreground text-sm">{emptyLine}</p>
        ) : layout === "graph" ? (
          <Suspense fallback={<Skeleton className="h-[28rem] w-full rounded-xl" />}>
            <RelationsGraph
              entity={entity}
              title={entityTitle ?? title ?? t("title")}
              nodes={neighbourhood.nodes}
              edges={neighbourhood.edges}
              groups={showTags ? [...shown, RELATION_GROUPS.tagged] : shown}
              hops={hops}
              onHopsChange={setHops}
              showTags={showTags}
              onShowTagsChange={setShowTags}
              loading={neighbourhood.isLoading}
              walkFailed={neighbourhood.walkFailed}
            />
          </Suspense>
        ) : layout === "carousel" ? (
          /* One shelf rather than a heading per kind of link: a carousel is
             pushed along, and stopping it at every heading would make it four
             short shelves. What each link says rides on its own card. */
          <Carousel className="relative">
            <CarouselContent className="-ml-4">
              {visible.map((edge) => {
                const group = groupOf(edge, shown);
                if (!group) return null;
                return (
                  <CarouselItem key={edge.id} className="basis-40 pl-4 sm:basis-44 md:basis-48">
                    <EntityCard
                      end={edge.other}
                      badge={t(`groups.${group.key}.title` as const)}
                      linkedAt={edge.created_at}
                      state={states.get(`${edge.other.type}:${edge.other.id}`)}
                      isOpen={edge.other.is_open}
                      onRemove={
                        canEdit && edge.provenance === "manual"
                          ? () => unrelate.mutate(edge)
                          : undefined
                      }
                      removing={unrelate.isPending}
                    />
                  </CarouselItem>
                );
              })}
            </CarouselContent>
            <CarouselPrevious className="left-0 -translate-x-1/2" />
            <CarouselNext className="right-0 translate-x-1/2" />
          </Carousel>
        ) : (
          shown.map((group) => {
            const edges = grouped.get(group.key) ?? [];
            if (edges.length === 0) return null;
            const GroupIcon = group.icon;
            return (
              <section key={group.key} className={layout === "rows" ? "space-y-1" : "space-y-3"}>
                <div
                  className={cn(
                    "flex items-center gap-2",
                    layout === "rows" && "px-2 text-muted-foreground"
                  )}
                  // A list keeps its headings to one line; why a group cannot be
                  // added to is under the pointer there.
                  title={layout === "rows" && !group.assertable ? t("derived") : undefined}
                >
                  <GroupIcon
                    className={cn(
                      "text-muted-foreground",
                      layout === "rows" ? "h-3.5 w-3.5" : "h-4 w-4"
                    )}
                  />
                  <h3 className={cn("font-medium", layout === "rows" ? "text-xs" : "text-sm")}>
                    {t(`groups.${group.key}.title`)}
                  </h3>
                  {(() => {
                    // "1 of 3 still open" where the ends can say, a plain count
                    // where they cannot. A bare 3 under Blocked by outlives the
                    // work it describes, which is most of why nobody trusted it.
                    const tally = openTally(edges);
                    return (
                      <span className="text-muted-foreground text-xs">
                        {tally
                          ? t("openOf", { open: tally.open, total: tally.total })
                          : edges.length}
                      </span>
                    );
                  })()}
                </div>
                {group.assertable || layout === "rows" ? null : (
                  <p className="text-muted-foreground text-xs">{t("derived")}</p>
                )}
                {/* Sized by the container rather than by viewport breakpoints:
                    this section sits full-width on a project page and in a half
                    column beside a task form, and a fixed column count makes a
                    card enormous in the first and cramped in the second.
                    `auto-fill` rather than `auto-fit` so three cards in a wide
                    row stay card-sized instead of stretching to fill it. */}
                <div className={layout === "rows" ? ROW_LIST : CARD_GRID}>
                  {edges.map((edge: RelationshipRead) => (
                    <EntityCard
                      key={edge.id}
                      end={edge.other}
                      variant={layout === "rows" ? "compact" : "card"}
                      linkedAt={edge.created_at}
                      state={states.get(`${edge.other.type}:${edge.other.id}`)}
                      isOpen={edge.other.is_open}
                      /* A link read out of a body is not one to take back here:
                         editing the words is how it is withdrawn. */
                      onRemove={
                        canEdit && edge.provenance === "manual"
                          ? () => unrelate.mutate(edge)
                          : undefined
                      }
                      removing={unrelate.isPending}
                    />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </CollapsibleContent>

      {adding ? (
        <AddLinkDialog
          entity={entity}
          initiativeId={initiativeId}
          anchorTool={anchorTool}
          assertable={assertable}
          canUpload={canUpload}
          initialFile={droppedFile}
          onClose={closeDialog}
        />
      ) : null}
    </Collapsible>
  );
};
