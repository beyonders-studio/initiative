import {
  DndContext,
  type DragEndEvent,
  type DragMoveEvent,
  KeyboardSensor,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { Link } from "@tanstack/react-router";
import { CircleChevronRight, Home } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  Tool,
  type WikiPageHeading,
  WikiPageKind,
  type WikiPageSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { fileIcon } from "@/lib/fileIcon";
import { cn } from "@/lib/utils";

/** Which of a row's three bands a dragged page is over. */
type DropIntent = "before" | "into" | "after";

/** Where a drag would land, as the list is drawing it. */
interface Landing {
  /** The row it would land on, as {@link rowKey} names it. */
  key: string;
  intent: DropIntent;
}

/**
 * What names a row in a drag.
 *
 * Not the id: a page and a borrowed file are different rows of the same
 * list and can both be number 11, so the kind goes in the name — otherwise a
 * drag on one marks the other.
 */
const rowKey = (row: Pick<WikiPageSummary, "id" | "kind">) => `${row.kind}:${row.id}`;

/**
 * Which of the three bands of a row a dragged row may land in.
 *
 * Two rules, and between them they are the whole of what the tree permits:
 *
 * A page cannot be filed inside itself or inside anything filed under it —
 * that would take the branch out of the wiki, and the server refuses it too.
 *
 * A borrowed file is filed like a page — at the top or under any page,
 * this wiki's record of where it put it — but it never holds anything itself,
 * so only its edges answer a drag.
 */
export const dropIntents = (
  dragged: Pick<WikiPageSummary, "id" | "kind">,
  target: Pick<WikiPageSummary, "id" | "kind" | "parent_page_id">,
  descendantsOfDragged: ReadonlySet<number>
): DropIntent[] => {
  if (rowKey(dragged) === rowKey(target)) return [];
  // Only pages have anything under them, so only a page can be a descendant.
  if (target.kind === WikiPageKind.page && descendantsOfDragged.has(target.id)) return [];
  return target.kind === WikiPageKind.file ? ["before", "after"] : ["before", "into", "after"];
};

/**
 * The indent, and the line down it.
 *
 * One rule for every level, taken from the initiative section: a child list is
 * inset by `ml-3` and carries a `border-l` in the wiki's own colour. Depth
 * comes from the nesting and from nothing else.
 */
const BRANCH = "ml-3 space-y-0.5 border-l";

/** A heading, and the headings written under it. */
interface HeadingNode {
  heading: WikiPageHeading;
  children: HeadingNode[];
}

/**
 * A page's headings as a tree.
 *
 * The server sends them flat and in order; the nesting is inferred from the
 * levels alone. A shallower heading closes every deeper one still open, so a
 * page that starts at `h2` puts its `h2`s at the top level, and one that jumps
 * `h1` to `h3` files the `h3` under the `h1` rather than inventing an empty
 * `h2` to sit between them.
 */
export const buildHeadingTree = (headings: readonly WikiPageHeading[]): HeadingNode[] => {
  const roots: HeadingNode[] = [];
  const open: HeadingNode[] = [];

  for (const heading of headings) {
    const node: HeadingNode = { heading, children: [] };
    while (open.length > 0 && open[open.length - 1].heading.level >= heading.level) {
      open.pop();
    }
    const parent = open[open.length - 1];
    if (parent) parent.children.push(node);
    else roots.push(node);
    open.push(node);
  }
  return roots;
};

/**
 * One heading of a page.
 *
 * A link rather than a button: a heading has an address — its page, plus the
 * anchor the editor stamps on it when it renders — so it can be opened from a
 * page you are not currently on, and opened in a new tab like anything else.
 */
const WikiHeadingRow = ({
  node,
  href,
  hrefOf,
  accentColor,
}: {
  node: HeadingNode;
  href: string;
  hrefOf: (anchor: string) => string;
  accentColor?: string | null;
}) => (
  <SidebarMenuItem>
    <SidebarMenuButton asChild size="sm" className="min-w-0 text-muted-foreground">
      <Link to={hrefOf(node.heading.anchor)} className="min-w-0">
        <span className="min-w-0 flex-1 truncate text-left">{node.heading.text}</span>
      </Link>
    </SidebarMenuButton>
    {node.children.length > 0 ? (
      <div className={BRANCH} style={{ borderColor: accentColor || undefined }}>
        <SidebarMenu>
          {node.children.map((child) => (
            <WikiHeadingRow
              key={child.heading.anchor}
              node={child}
              href={href}
              hrefOf={hrefOf}
              accentColor={accentColor}
            />
          ))}
        </SidebarMenu>
      </div>
    ) : null}
  </SidebarMenuItem>
);

/**
 * One page, and — while you are reading it — what is on it.
 *
 * A wiki's pages do not nest: the structure of a wiki is the pages beside each
 * other and the headings inside each one. So a row's disclosure opens its
 * headings, which is the only thing a page contains.
 *
 * The parts are an initiative row's: the same chevron, the same guide line, and
 * a title that is a link because a page is an address.
 *
 * Declared at module scope rather than inside {@link WikiPageTree}: a component
 * defined during a render is a new type on every render, so React would remount
 * the list each time, and a drag in progress would lose the rows it is tracking.
 */
const WikiPageRow = ({
  page,
  active,
  isHome,
  href,
  draggable: draggableRows,
  landing,
  open,
  onToggle,
  accentColor,
  rowMenu,
  children,
}: {
  page: WikiPageSummary;
  active: boolean;
  isHome: boolean;
  href: string;
  draggable: boolean;
  landing: Landing | null;
  open: boolean;
  onToggle: () => void;
  accentColor?: string | null;
  rowMenu?: ReactNode;
  /** The rows for what is filed under this page. */
  children: ReactNode[];
}) => {
  const { t } = useTranslation(["wikis", "common"]);
  const unread = useUnreadTree();
  const showing = landing?.key === rowKey(page) ? landing.intent : null;
  // Every page's headings come with the page, so a row is collapsible from the
  // moment it is drawn — nobody has to open a page to find out that it has
  // anything in it.
  const headings = useMemo(() => buildHeadingTree(page.headings), [page.headings]);
  // A row opens onto two different things: the pages filed under it, and the
  // headings written on it. Both are what is "inside" this page, so both sit
  // behind the one disclosure — the pages first, because they are places and
  // the headings are only parts of this one.
  const expandable = headings.length > 0 || children.length > 0;
  const isFile = page.kind === WikiPageKind.file;
  // A borrowed file is marked as the kind of file it is — a PDF, a
  // spreadsheet, a link to a design tool — the same mark it has everywhere.
  const { Icon: FileIcon, colorClass: fileColor } = fileIcon({
    file_type: page.file_type,
    smart_link_url: page.smart_link_url,
  });

  // Pages and borrowed files are one list, and one list is arranged as a
  // whole — so a file is dragged, and dropped onto, like anything else.
  const movable = draggableRows;
  const key = rowKey(page);
  const draggable = useDraggable({ id: key, disabled: !movable });
  const droppable = useDroppable({ id: key, disabled: !movable });
  // One element is both ends of the gesture — what you pick up and what you
  // drop onto — and dnd-kit hands out a ref for each.
  const setRowRef = (node: HTMLElement | null) => {
    draggable.setNodeRef(node);
    droppable.setNodeRef(node);
  };

  return (
    <SidebarMenuItem>
      <Collapsible open={open} onOpenChange={onToggle}>
        <div
          ref={setRowRef}
          {...draggable.listeners}
          {...draggable.attributes}
          className={cn(
            "group/page flex min-w-0 items-center gap-1 rounded-md",
            movable && "cursor-grab active:cursor-grabbing",
            draggable.isDragging && "opacity-40",
            showing === "before" && "border-primary border-t-2",
            showing === "after" && "border-primary border-b-2",
            // Filed INSIDE this one, which is a different promise from landing
            // beside it, so it is drawn differently.
            showing === "into" && "ring-1 ring-primary ring-inset"
          )}
        >
          <div className="flex min-w-0 flex-1 items-center">
            {/* One column at the head of every row, saying what the row is and
                opening what is inside it. A page shows a disclosure; a
                file shows the tool it comes from, because that is the more
                useful of the two things to know about a row you did not write
                here — and it opens the headings all the same. */}
            {expandable ? (
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  aria-label={open ? t("pages.collapse") : t("pages.expand")}
                >
                  {isFile ? (
                    <FileIcon className={cn("size-4", fileColor)} />
                  ) : (
                    <CircleChevronRight
                      className={cn("h-4 w-4 transition-transform", open && "rotate-90")}
                      style={{ color: accentColor || undefined }}
                    />
                  )}
                </Button>
              </CollapsibleTrigger>
            ) : isFile ? (
              <span className="flex h-7 w-7 shrink-0 items-center justify-center">
                <span className="sr-only">{t("files.openFile")}</span>
                <FileIcon className={cn("size-4", fileColor)} aria-hidden />
              </span>
            ) : (
              <span className="h-7 w-7 shrink-0" />
            )}

            <SidebarMenuButton asChild size="sm" isActive={active} className="min-w-0 flex-1">
              <Link to={href} className="flex min-w-0 items-center gap-2" title={page.title}>
                {/* A draft reads as unfinished at a glance: only the people who
                    can write here are shown it at all. */}
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    page.is_draft && "text-muted-foreground"
                  )}
                >
                  {page.title || t("common:untitled")}
                </span>
                {/* A borrowed file is read as the file it is. */}
                {unread.hasSubject(
                  page.community_id,
                  isFile ? Tool.file : SearchEntityType.wiki_page,
                  page.id
                ) ? (
                  <UnreadDot />
                ) : null}
                {page.is_draft ? (
                  <span className="shrink-0 rounded border px-1 text-3xs text-muted-foreground uppercase">
                    {t("pages.draft")}
                  </span>
                ) : null}
                {isHome ? (
                  <Home
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label={t("pages.isHome")}
                  />
                ) : null}
              </Link>
            </SidebarMenuButton>
          </div>

          {rowMenu}
        </div>

        {expandable ? (
          <CollapsibleContent className={BRANCH} style={{ borderColor: accentColor || undefined }}>
            <SidebarMenu>
              {headings.map((node) => (
                <WikiHeadingRow
                  key={node.heading.anchor}
                  node={node}
                  href={href}
                  hrefOf={(anchor) => `${href}#${anchor}`}
                  accentColor={accentColor}
                />
              ))}
              {children}
            </SidebarMenu>
          </CollapsibleContent>
        ) : null}
      </Collapsible>
    </SidebarMenuItem>
  );
};

interface WikiPageTreeProps {
  pages: WikiPageSummary[];
  /** Which page is open, so the list can mark it and show what is on it. */
  activePageId?: number | null;
  /** The wiki's chosen home page, marked so it reads as the way in. */
  homePageId?: number | null;
  /** The wiki's accent, so its branches read as its own the way an initiative's do. */
  accentColor?: string | null;
  /** Builds the link for a page. The list does not know the route shape. */
  hrefOf: (page: WikiPageSummary) => string;
  /**
   * What a row offers at its end — drawn by the caller, because what can be
   * done to a page is the caller's business and not this component's.
   */
  renderRowMenu?: (page: WikiPageSummary) => ReactNode;
  /**
   * Where a dragged page was dropped: what it is now filed under, and its
   * index among what else is filed there. Omitted when the reader may not
   * write, which is also what makes rows undraggable.
   */
  onMove?: (page: WikiPageSummary, parentPageId: number | null, position: number) => void;
  /**
   * Which rows are open, where the caller is also drawing a control over them
   * — the open/close-all button. Omitted, the tree keeps its own.
   */
  expansion?: WikiTreeExpansion;
  className?: string;
}

/**
 * A wiki's pages, what is filed under each, and the headings written on them.
 *
 * Two structures meet in this one column. Pages file under pages, which is the
 * wiki's shape and lives in the table; the headings of a page are what is
 * written ON it, and live in its body. A row's disclosure opens both, pages
 * first — they are places, and a heading is only part of one.
 *
 * Dragging says both things at once: the middle of a row files the dragged
 * page under it, and the quarter at each edge places it before or after as a
 * sibling.
 *
 * Rows are links rather than buttons — a page is an address, and opening one in
 * a new tab is something people do with a handbook. The row is also the surface
 * you drag: the sensors want six pixels of travel first, so a click only ever
 * follows the link.
 */
/**
 * Which rows are open.
 *
 * Held in a hook of its own so a control BESIDE the tree — the open/close-all
 * button over the sidebar — can act on the same set the rows toggle. A tree
 * given none keeps its own, which is what every other caller wants.
 *
 * `openable` is every row that has something inside it: pages filed under it,
 * or headings written on it. Both are what a disclosure opens, so both count
 * towards "everything is open".
 */
export const useWikiTreeExpansion = (pages: readonly WikiPageSummary[]) => {
  // Closed is the default: this column is a list of pages, and a page's
  // headings are what you ask for once you are interested in that page. So
  // this records the pages somebody has deliberately opened.
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());

  const openable = useMemo(() => {
    const parents = new Set(
      pages.map((page) => page.parent_page_id).filter((id): id is number => id != null)
    );
    return pages
      .filter((page) => parents.has(page.id) || page.headings.length > 0)
      .map((page) => page.id);
  }, [pages]);

  const allOpen = openable.length > 0 && openable.every((id) => expanded.has(id));

  return {
    expanded,
    setExpanded,
    /** Whether the button should offer to close rather than open. */
    allOpen,
    /** Nothing to open or close — the button has no work, so it is not shown. */
    isEmpty: openable.length === 0,
    toggleAll: () => setExpanded(allOpen ? new Set<number>() : new Set(openable)),
  };
};

export type WikiTreeExpansion = ReturnType<typeof useWikiTreeExpansion>;

export const WikiPageTree = ({
  pages,
  activePageId,
  homePageId,
  accentColor,
  hrefOf,
  renderRowMenu,
  onMove,
  expansion,
  className,
}: WikiPageTreeProps) => {
  const { t } = useTranslation("wikis");

  // A tree nobody is driving from outside keeps its own set. The hook runs
  // either way — it has to, being a hook — and the caller's wins.
  const own = useWikiTreeExpansion(pages);
  const { expanded, setExpanded } = expansion ?? own;
  const toggle = (id: number) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Arriving at a page that is filed inside something opens what it is filed
  // inside, so the column shows where you are rather than a closed row you
  // have to guess at. Only ever opened — what somebody opened for themselves
  // stays open — and only once per page, so collapsing a branch you are
  // standing in is allowed to hold.
  const revealed = useRef<number | null>(null);
  useEffect(() => {
    if (activePageId == null || revealed.current === activePageId) return;
    const active = pages.find((page) => page.id === activePageId);
    if (!active) return;
    revealed.current = activePageId;

    const byId = new Map(pages.map((page) => [page.id, page]));
    const ancestors: number[] = [];
    let parent = active.parent_page_id ?? null;
    while (parent !== null && !ancestors.includes(parent)) {
      ancestors.push(parent);
      parent = byId.get(parent)?.parent_page_id ?? null;
    }
    if (ancestors.length === 0) return;
    setExpanded((previous) => new Set([...previous, ...ancestors]));
    // `setExpanded` is a `useState` setter either way — its own or the
    // caller's — so naming it here costs nothing and keeps the rule honest.
  }, [activePageId, pages, setExpanded]);

  // The same activation distances the community rail uses, so a drag started
  // anywhere in the sidebar feels the same.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor)
  );

  const [landing, setLanding] = useState<Landing | null>(null);

  /** The rows filed in each place, in the order they arrived — which is the
   *  order the server sent, and therefore reading order. */
  const filed = useMemo(() => {
    const byParent = new Map<number | null, WikiPageSummary[]>();
    for (const page of pages) {
      const parent = page.parent_page_id ?? null;
      const group = byParent.get(parent) ?? [];
      group.push(page);
      byParent.set(parent, group);
    }
    return byParent;
  }, [pages]);

  /** Every page beneath a given one. */
  const descendantsOf = (rootId: number): Set<number> => {
    const found = new Set<number>();
    const frontier = [rootId];
    while (frontier.length > 0) {
      const id = frontier.pop();
      if (id === undefined) continue;
      for (const child of filed.get(id) ?? []) {
        // A file is filed under pages but holds nothing itself.
        if (child.kind !== WikiPageKind.page || found.has(child.id)) continue;
        found.add(child.id);
        frontier.push(child.id);
      }
    }
    return found;
  };

  const rowFor = (key: string | number | null) =>
    pages.find((candidate) => rowKey(candidate) === String(key)) ?? null;

  const intentsFor = (dragged: WikiPageSummary | null, target: WikiPageSummary | null) =>
    dragged && target
      ? dropIntents(dragged, target, descendantsOf(dragged.id))
      : ([] as DropIntent[]);

  const landingOf = (event: DragMoveEvent): Landing | null => {
    const over = event.over;
    const moving = event.active.rect.current.translated;
    if (!over || !moving) return null;

    const target = rowFor(over.id);
    const allowed = intentsFor(rowFor(event.active.id), target);
    if (!target || allowed.length === 0) return null;

    const centre = moving.top + moving.height / 2;
    const offset = (centre - over.rect.top) / over.rect.height;
    const intent: DropIntent = !allowed.includes("into")
      ? offset < 0.5
        ? "before"
        : "after"
      : offset < 0.25
        ? "before"
        : offset > 0.75
          ? "after"
          : "into";
    return { key: rowKey(target), intent };
  };

  const clearDrag = () => setLanding(null);

  const onDragMove = (event: DragMoveEvent) => {
    const next = landingOf(event);
    if (next?.key !== landing?.key || next?.intent !== landing?.intent) {
      setLanding(next);
    }
  };

  const onDragEnd = (event: DragEndEvent) => {
    const page = rowFor(event.active.id);
    const dropped = landing;
    clearDrag();
    if (!onMove || !page || !dropped) return;

    const target = rowFor(dropped.key);
    if (!target || !intentsFor(page, target).includes(dropped.intent)) return;

    if (dropped.intent === "into") {
      // At the end of what is already filed there, which is where a thing put
      // INTO something goes — nobody dropping onto a folder means "first".
      onMove(page, target.id, (filed.get(target.id) ?? []).length);
      return;
    }
    // A sibling drop: its index among the target's own neighbours, counted
    // without the page being moved so the number means the same before and
    // after it lands.
    const parent = target.parent_page_id ?? null;
    const neighbours = (filed.get(parent) ?? []).filter(
      (candidate) => rowKey(candidate) !== rowKey(page)
    );
    const index = neighbours.findIndex((candidate) => rowKey(candidate) === rowKey(target));
    if (index < 0) return;
    onMove(page, parent, dropped.intent === "before" ? index : index + 1);
  };

  /** One row, and under it every row filed there. */
  const rowsUnder = (parent: number | null): ReactNode[] =>
    (filed.get(parent) ?? []).map((page) => (
      <WikiPageRow
        key={`${page.kind}:${page.id}`}
        page={page}
        active={page.id === activePageId}
        isHome={page.id === homePageId}
        href={hrefOf(page)}
        draggable={Boolean(onMove)}
        landing={landing}
        open={expanded.has(page.id)}
        onToggle={() => toggle(page.id)}
        accentColor={accentColor}
        rowMenu={renderRowMenu?.(page)}
      >
        {/* Only a page has rows under it — a file's id can be a page's
            too, and must not collect that page's children. */}
        {page.kind === WikiPageKind.page ? rowsUnder(page.id) : []}
      </WikiPageRow>
    ));

  if (pages.length === 0) {
    return (
      <p className={cn("px-2 py-1.5 text-muted-foreground text-sm", className)}>
        {t("pages.empty")}
      </p>
    );
  }

  return (
    <nav className={className} aria-label={t("pages.title")}>
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragMove={onDragMove}
        onDragEnd={onDragEnd}
        onDragCancel={clearDrag}
      >
        <SidebarMenu>{rowsUnder(null)}</SidebarMenu>
      </DndContext>
    </nav>
  );
};
