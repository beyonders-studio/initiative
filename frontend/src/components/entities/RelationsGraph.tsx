import { SigmaContainer, useRegisterEvents, useSigma } from "@react-sigma/core";
import { createNodeImageProgram } from "@sigma/node-image";
import { useNavigate } from "@tanstack/react-router";
import Graphology from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { drawDiscNodeLabel, type NodeHoverDrawingFunction } from "sigma/rendering";
import { animateNodes } from "sigma/utils";

import "@react-sigma/core/lib/style.css";

import {
  EndpointKind,
  type EndpointRef,
  type RelatedEnd,
} from "@/api/generated/initiativeAPI.schemas";
import { type GraphEdge, type GraphNode, MAX_HOPS } from "@/hooks/useRelationships";
import { useTheme } from "@/hooks/useTheme";
import { useCommunityPath } from "@/lib/communityUrl";
import { themeColor, withAlpha } from "@/lib/cssColor";
import { iconDataUri } from "@/lib/iconSvg";
import { getInitials } from "@/lib/initials";
import { groupOf, isItem, type RelationGroup, relatedTarget } from "@/lib/relationships";
import { entityIcon, hitIcon, searchHitPath } from "@/lib/searchResults";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { getUserColorStyle } from "@/ui/lib/userColor";
import { SkeletonRegion } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";

/** How far out each ring of neighbours sits before the layout takes over. */
const RING = 10;
const CENTRE_KEY = "__centre__";

/**
 * Which of the theme's colours each heading takes.
 *
 * The five chart colours are the set a theme already picks for telling one
 * series from another, so a graph's links are told apart with the same palette
 * everything else in the app measures with — including whatever accent a
 * community chose. The two that fall outside it are the two that are not really
 * assertions: a reference read out of a body, and a label.
 */
const GROUP_VARIABLE: Record<string, string> = {
  attached: "--chart-2",
  blockedBy: "--chart-5",
  blocks: "--chart-4",
  partOf: "--chart-1",
  parts: "--chart-3",
  related: "--chart-2",
  referencedBy: "--muted-foreground",
  tagged: "--chart-4",
};

/** Where a colour lands if the theme has not been loaded yet. */
const FALLBACK: Record<string, string> = {
  "--chart-1": "#8b5cf6",
  "--chart-2": "#0ea5e9",
  "--chart-3": "#14b8a6",
  "--chart-4": "#f59e0b",
  "--chart-5": "#f43f5e",
  "--muted-foreground": "#94a3b8",
  "--card": "#ffffff",
  "--popover": "#ffffff",
  "--border": "#e2e8f0",
  "--foreground": "#0f172a",
  "--primary": "#6366f1",
  "--primary-foreground": "#ffffff",
};

/**
 * A kind's mark, as something a canvas can draw.
 *
 * Read from the very same icon the cards and the search results use, so a kind
 * cannot end up with one mark in a list and a different one in the picture.
 * Cached: the set of kinds is small and fixed, while the colours are not.
 */
const iconCache = new Map<string, string>();

const iconUri = (
  Icon: React.ComponentType<{ color?: string; strokeWidth?: number }>,
  colour: string,
  key: string
) => {
  const cacheKey = `${key}:${colour}`;
  const found = iconCache.get(cacheKey);
  if (found !== undefined) return found;
  const uri = iconDataUri(Icon, colour) ?? "";
  iconCache.set(cacheKey, uri);
  return uri;
};

/**
 * A person's face, or their initials in their own colour where they have no
 * picture — the same two an avatar anywhere else falls between.
 */
const faceUri = (end: RelatedEnd): string => {
  const picture = resolveUploadUrl(end.image_urls[0]);
  if (picture) return picture;
  const { backgroundColor, color } = getUserColorStyle(end.id);
  const initials = getInitials(end.title).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const markup = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12" fill="${backgroundColor}"/><text x="12" y="12" text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-size="9" font-weight="600" fill="${color}">${initials}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
};

/**
 * Icons inside their nodes.
 *
 * `keepWithinCircle` with room to spare: the mark is drawn into the circle
 * rather than over a square the circle is inscribed in, which is what had the
 * corners of every icon hanging outside its node.
 */
const NODE_PROGRAM = createNodeImageProgram({
  keepWithinCircle: true,
  padding: 0.28,
  drawingMode: "background",
});

/** A face fills its node but for a ring in the link's colour. */
const FACE_PROGRAM = createNodeImageProgram({
  keepWithinCircle: true,
  padding: 0.12,
  drawingMode: "background",
});

/**
 * The card behind a hovered node's name.
 *
 * Sigma's own draws a white box with a black shadow, whatever the page looks
 * like — which in a dark theme is a white card carrying white text. This is the
 * same shape in the theme's own colours, and the text is then drawn by sigma so
 * the two cannot fall out of step.
 */
const drawHover =
  (surface: string, border: string): NodeHoverDrawingFunction =>
  (context, data, settings) => {
    const size = settings.labelSize;
    context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;

    if (typeof data.label === "string") {
      const PADDING = 3;
      const width = Math.round(context.measureText(data.label).width + 6);
      const height = Math.round(size + 2 * PADDING);
      const radius = Math.max(data.size, size / 2) + PADDING;
      const angle = Math.asin(height / 2 / radius);
      const xDelta = Math.sqrt(Math.abs(radius ** 2 - (height / 2) ** 2));

      context.beginPath();
      context.moveTo(data.x + xDelta, data.y + height / 2);
      context.lineTo(data.x + radius + width, data.y + height / 2);
      context.lineTo(data.x + radius + width, data.y - height / 2);
      context.lineTo(data.x + xDelta, data.y - height / 2);
      context.arc(data.x, data.y, radius, angle, -angle);
      context.closePath();

      // A border rather than a shadow. Sigma's own drops a black one, which is
      // what a white card needs and a dark one disappears into; an outline in
      // the theme's own border colour separates the card on either.
      context.fillStyle = surface;
      context.fill();
      context.lineWidth = 1;
      context.strokeStyle = border;
      context.stroke();
    }

    drawDiscNodeLabel(context, data, settings);
  };

interface NodeAttrs {
  label: string;
  x: number;
  y: number;
  size: number;
  color: string;
  image: string;
  href?: string;
  /** Which program draws it: an icon, unless it is somebody's face. */
  type?: "face";
}

interface RelationsGraphProps {
  entity: EndpointRef;
  title: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: RelationGroup[];
  hops: number;
  onHopsChange: (hops: number) => void;
  showTags: boolean;
  onShowTagsChange: (showTags: boolean) => void;
  loading?: boolean;
  /** The walk further out failed, so only the first hop is drawn. */
  walkFailed?: boolean;
}

/** How hard the layout pushes, wherever it is asked to run. */
const LAYOUT = { gravity: 1.4, scalingRatio: 8, slowDown: 6, adjustSizes: true } as const;

/**
 * The picture settling, being pushed around, and being followed.
 *
 * There is no worker. A layout running in the background is a layout still
 * nudging things a fraction of a pixel for as long as the page is open, which is
 * what a graph shivering actually is — and its copy of the positions is what
 * kept dragging a node putting it straight back. The layout is run here instead,
 * in short bursts, at the two moments there is a reason for it: when the picture
 * is new, and while somebody is moving something.
 */
const Interactions = ({
  onOpen,
  version,
}: {
  onOpen: (href: string) => void;
  /** Changes when the picture is a different picture, so it settles again. */
  version: string;
}) => {
  const sigma = useSigma();
  const registerEvents = useRegisterEvents();
  const dragging = useRef<string | null>(null);
  const moved = useRef(false);

  /** Where the layout would put everything, from where it is now. */
  const relax = useCallback(
    (iterations: number) => {
      const graph = sigma.getGraph();
      if (graph.order < 2) return null;
      return forceAtlas2(graph, {
        iterations,
        settings: { ...forceAtlas2.inferSettings(graph), ...LAYOUT },
      });
    },
    [sigma]
  );

  /**
   * A new picture arranges itself, visibly.
   *
   * Worked out in one go and then *eased* into place from the ring the nodes
   * were seeded in, rather than crept towards a tick at a time. Same
   * destination, and you can see it happen — which is what says "these belong
   * together" better than the finished picture does.
   */
  useEffect(() => {
    const targets = relax(300);
    if (!targets) return;
    return animateNodes(sigma.getGraph(), targets, {
      duration: 700,
      easing: "quadraticInOut",
    });
  }, [sigma, relax, version]);

  useEffect(() => {
    registerEvents({
      downNode: (event) => {
        dragging.current = event.node;
        moved.current = false;
        const graph = sigma.getGraph();
        graph.setNodeAttribute(event.node, "highlighted", true);
        // Held, not pushed: the layout treats it as immovable, so everything
        // else arranges itself around wherever it is being put.
        graph.setNodeAttribute(event.node, "fixed", true);
      },
      mousemovebody: (event) => {
        const node = dragging.current;
        if (!node) return;
        moved.current = true;
        const graph = sigma.getGraph();
        const position = sigma.viewportToGraph(event);
        graph.setNodeAttribute(node, "x", position.x);
        graph.setNodeAttribute(node, "y", position.y);
        // A few steps per frame: enough that neighbours are visibly dragged
        // along and the rest get out of the way, few enough to keep up.
        forceAtlas2.assign(graph, {
          iterations: 2,
          settings: { ...forceAtlas2.inferSettings(graph), ...LAYOUT },
        });
        // Stop the camera panning while a node is being carried.
        event.preventSigmaDefault();
        event.original.preventDefault();
        event.original.stopPropagation();
      },
      mouseup: () => {
        const node = dragging.current;
        dragging.current = null;
        if (!node) return;
        const graph = sigma.getGraph();
        graph.removeNodeAttribute(node, "highlighted");
        // Let go and it joins in again rather than staying pinned where it was
        // dropped — and everything takes a moment to take up the slack.
        graph.removeNodeAttribute(node, "fixed");
        const targets = relax(60);
        if (targets) {
          animateNodes(graph, targets, { duration: 350, easing: "quadraticOut" });
        }
      },
      clickNode: (event) => {
        if (moved.current) return;
        const href = sigma.getGraph().getNodeAttribute(event.node, "href");
        if (typeof href === "string" && href) onOpen(href);
      },
    });
  }, [registerEvents, sigma, onOpen, relax]);

  return null;
};

/**
 * Everything connected to one thing, as a picture you can move around in.
 *
 * Seeded as a ring per hop — the thing itself in the middle, what it touches
 * around it, what those touch further out — and then handed to a layout: things
 * repel, links pull, and a node has mass, so dragging one drags its neighbours
 * after it while the rest move aside. Wheel to zoom, drag the background to pan;
 * the wheel zooms the picture rather than scrolling the page past it, which is
 * what a graph you are reading is for.
 *
 * The ring is a seed rather than the answer, but a deterministic one, so the
 * same links start from the same shape every time instead of being flung
 * somewhere new by the first few ticks.
 */
export const RelationsGraph = ({
  entity,
  title,
  nodes,
  edges,
  groups,
  hops,
  onHopsChange,
  showTags,
  onShowTagsChange,
  loading,
  walkFailed,
}: RelationsGraphProps) => {
  const { t } = useTranslation(["relations", "search"]);
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const { resolvedTheme } = useTheme();
  const centreKey = `${entity.type}:${entity.id}`;

  /** The theme's own colours, read fresh whenever the theme changes. */
  const palette = useMemo(() => {
    const of = (variable: string) => themeColor(variable, FALLBACK[variable] ?? "#94a3b8");
    return {
      node: of("--card"),
      label: of("--foreground"),
      surface: of("--popover"),
      border: of("--border"),
      centre: of("--primary"),
      centreMark: of("--primary-foreground"),
      groups: Object.fromEntries(
        Object.entries(GROUP_VARIABLE).map(([key, variable]) => [key, of(variable)])
      ) as Record<string, string>,
      // `resolvedTheme` is not read here, but it is what makes this run again.
      theme: resolvedTheme,
    };
  }, [resolvedTheme]);

  const colourFor = useCallback(
    (key: string | undefined) => palette.groups[key ?? "related"] ?? palette.label,
    [palette]
  );

  const graph = useMemo(() => {
    const built = new Graphology<NodeAttrs>();
    const order = new Map<string, number>(groups.map((group, index) => [group.key, index]));

    const groupFor = new Map<string, string | undefined>();
    for (const edge of edges) {
      if (!groupFor.has(edge.to)) groupFor.set(edge.to, groupOf(edge, groups)?.key);
    }

    built.addNode(CENTRE_KEY, {
      label: title,
      x: 0,
      y: 0,
      size: 18,
      color: palette.centre,
      // The middle is what the links are read from, which is never a person.
      image:
        entity.type === EndpointKind.user
          ? ""
          : iconUri(entityIcon(entity.type), palette.centreMark, `centre:${entity.type}`),
    });

    const byDepth = new Map<number, GraphNode[]>();
    for (const node of nodes) {
      byDepth.set(node.depth, [...(byDepth.get(node.depth) ?? []), node]);
    }

    for (const [depth, ring] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
      const sorted = [...ring].sort((a, b) => {
        const ak = groupFor.get(`${a.ref.type}:${a.ref.id}`);
        const bk = groupFor.get(`${b.ref.type}:${b.ref.id}`);
        return (order.get(ak ?? "") ?? 99) - (order.get(bk ?? "") ?? 99);
      });
      sorted.forEach((node, index) => {
        // From the top, clockwise. An outer ring is offset half a step so its
        // nodes sit between the ones inside rather than behind them.
        const angle =
          (index / Math.max(sorted.length, 1)) * Math.PI * 2 -
          Math.PI / 2 +
          (depth % 2 === 0 ? Math.PI / Math.max(sorted.length, 1) : 0);
        const key = `${node.ref.type}:${node.ref.id}`;
        const colour = colourFor(groupFor.get(key));
        const target = isItem(node.end) ? relatedTarget(node.end) : null;
        const path = target ? searchHitPath(target) : null;
        built.addNode(key, {
          label: node.end.title?.trim() || t("untitled"),
          x: Math.cos(angle) * RING * depth,
          y: -Math.sin(angle) * RING * depth,
          // Further out is smaller: the middle is the subject and a third hop
          // is context.
          size: Math.max(9, 15 - (depth - 1) * 3),
          ...(target
            ? {
                // The circle takes the theme's own surface and the mark inside
                // it takes the link's colour, so the kind and the link both
                // read whether the page is light or dark.
                color: palette.node,
                image: iconUri(hitIcon(target), colour, node.ref.type),
                href: path ? gp(path) : undefined,
              }
            : {
                // A person is their face, ringed in the link's colour, and
                // opens their profile, which is outside any community.
                type: "face" as const,
                color: colour,
                image: faceUri(node.end),
                href: node.end.handle ? `/u/${node.end.handle}` : undefined,
              }),
        });
      });
    }

    for (const edge of edges) {
      const from = edge.from === centreKey ? CENTRE_KEY : edge.from;
      const to = edge.to === centreKey ? CENTRE_KEY : edge.to;
      if (!built.hasNode(from) || !built.hasNode(to) || built.hasEdge(from, to)) continue;
      const colour = colourFor(groupOf(edge, groups)?.key);
      // A link read out of a body was not asserted by anybody, so it is drawn as
      // the weaker claim it is: fainter and thinner. Not dashed — sigma draws
      // edges with one of the programs it was given, and a dashed one is not
      // among them.
      const asserted = edge.provenance === "manual";
      built.addEdge(from, to, {
        color: asserted ? colour : withAlpha(colour, 0.4),
        size: asserted ? 2 : 1,
      });
    }
    return built;
  }, [nodes, edges, groups, title, centreKey, gp, t, entity.type, entity.id, palette, colourFor]);

  const shownGroups = useMemo(
    () => groups.filter((group) => edges.some((edge) => groupOf(edge, groups)?.key === group.key)),
    [edges, groups]
  );

  /** What is drawn, as one value: a different one is a different picture. */
  const version = `${graph.order}:${graph.size}:${resolvedTheme}`;

  if (nodes.length === 0) {
    return loading ? (
      <SkeletonRegion>
        <Skeleton className="h-[28rem] w-full rounded-xl" />
      </SkeletonRegion>
    ) : (
      <p className="text-muted-foreground text-sm">{t("empty")}</p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-muted-foreground text-xs">{t("graph.hops")}</span>
        {Array.from({ length: MAX_HOPS }, (_, index) => index + 1).map((step) => (
          <Button
            key={step}
            type="button"
            size="sm"
            variant={step === hops ? "secondary" : "ghost"}
            className="h-7 w-7 p-0 text-xs"
            onClick={() => onHopsChange(step)}
            aria-pressed={step === hops}
            aria-label={t("graph.hopsN", { count: step })}
          >
            {step}
          </Button>
        ))}
        {/* Off by default: a tag is carried by everything carrying it, so one
            hop through a popular one reaches most of the community. */}
        <label
          htmlFor="relations-graph-tags"
          className="ml-2 flex cursor-pointer items-center gap-1.5 text-muted-foreground text-xs"
        >
          <Checkbox
            id="relations-graph-tags"
            checked={showTags}
            onCheckedChange={(next) => onShowTagsChange(next === true)}
          />
          {t("graph.showTags")}
        </label>
        {loading ? (
          <span className="ml-1 text-muted-foreground text-xs">{t("graph.walking")}</span>
        ) : walkFailed ? (
          <span role="status" className="ml-1 text-muted-foreground text-xs">
            {t("graph.walkFailed")}
          </span>
        ) : null}
      </div>

      <section
        className="h-[28rem] w-full overflow-hidden rounded-xl border bg-muted/20"
        aria-label={t("graph.alt", { title, count: nodes.length })}
      >
        <SigmaContainer
          graph={graph}
          /* The library paints its own white behind the picture. Cleared, so the
             card underneath shows through and the graph is whatever colour the
             page is. */
          style={
            {
              height: "100%",
              width: "100%",
              "--sigma-background-color": "transparent",
            } as React.CSSProperties
          }
          settings={{
            allowInvalidContainer: true,
            renderLabels: true,
            labelDensity: 0.9,
            labelColor: { color: palette.label },
            defaultDrawNodeHover: drawHover(palette.surface, palette.border),
            defaultEdgeType: "line",
            defaultNodeType: "image",
            nodeProgramClasses: { image: NODE_PROGRAM, face: FACE_PROGRAM },
            zIndex: true,
          }}
        >
          <Interactions onOpen={(href) => navigate({ to: href })} version={version} />
        </SigmaContainer>
      </section>

      {/* What the colours mean, for the ones actually on screen. */}
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {shownGroups.map((group) => (
          <li key={group.key} className="flex items-center gap-1.5 text-muted-foreground text-xs">
            <span
              aria-hidden
              className="h-0.5 w-4 rounded-full"
              style={{ backgroundColor: colourFor(group.key) }}
            />
            {t(`groups.${group.key}.title`)}
          </li>
        ))}
      </ul>
    </div>
  );
};
