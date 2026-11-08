import { formatAxisValue } from "@/lib/widgets/format";
import type { BoardCard, SceneNode } from "@/lib/widgets/sceneSpec";
import { toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "board" }>;

/**
 * Rows dealt into columns.
 *
 * What a column stands for was decided by the widget and arrives already made,
 * so nothing here knows about statuses or assignees — it draws columns of cards
 * and a count per column, and that is the whole contract.
 *
 * Read-only, and visibly so: a card is a `<div>`, not a drag handle. A
 * dashboard reads and never writes, so there is nothing to drop a card onto and
 * no affordance suggesting otherwise.
 */
export function BoardNode({ node }: { node: Node }) {
  return (
    <div className="flex h-full w-full gap-2 overflow-x-auto overflow-y-hidden pb-1">
      {node.columns.map((column, index) => (
        <Column
          // biome-ignore lint/suspicious/noArrayIndexKey: two columns can carry the same label (a board grouped by a property with duplicate option labels), so position is the only identity a column has
          key={index}
          column={column}
        />
      ))}
    </div>
  );
}

function Column({ column }: { column: Node["columns"][number] }) {
  const count = column.total ?? column.cards.length;
  return (
    <section
      className="flex h-full w-56 min-w-56 flex-col rounded-md bg-muted/40"
      aria-label={column.label}
    >
      <header className="flex shrink-0 items-baseline gap-2 px-2 py-1.5">
        <h4 className="min-w-0 flex-1 truncate font-medium text-xs">{column.label}</h4>
        {column.caption && (
          <span className="shrink-0 text-2xs text-muted-foreground">{column.caption}</span>
        )}
        <span className="shrink-0 text-muted-foreground text-xs tabular-nums">{count}</span>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-1.5 pb-1.5">
        {column.cards.map((card, index) => (
          <Card
            // biome-ignore lint/suspicious/noArrayIndexKey: scene cards carry no id — the widget already fixed the order, so position is the card's identity
            key={index}
            card={card}
          />
        ))}
      </div>
    </section>
  );
}

function Card({ card }: { card: BoardCard }) {
  // The edge is the only place a card's tone is painted: a whole tinted card
  // fights the theme's own surfaces, and a stripe reads at a glance.
  const edge = card.tone ? toneColor(card.tone) : undefined;
  return (
    <article
      // `shrink-0` is load-bearing, not decoration. The column is a flex
      // column that scrolls, and a flex item's automatic minimum size is zero
      // once it hides its own overflow — which this card does, to clip a long
      // title. Without it a column of any length shares its height out among
      // the cards instead of overflowing: at 170 cards each is a hairline with
      // its text spilling over the next, and there is nothing to scroll.
      className="shrink-0 overflow-hidden rounded border border-border/60 bg-card"
      style={edge ? { borderLeftColor: edge, borderLeftWidth: 3 } : undefined}
    >
      <div className="px-2 py-1.5">
        <p className="line-clamp-2 text-xs leading-snug">{card.title}</p>
        {card.chips && card.chips.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {card.chips.map((chip, index) => (
              <span
                // biome-ignore lint/suspicious/noArrayIndexKey: chips are plain strings a card may legitimately repeat, so position is their identity
                key={index}
                className="max-w-full truncate rounded-sm bg-muted px-1 py-px text-3xs text-muted-foreground"
              >
                {chip}
              </span>
            ))}
          </div>
        )}
        {(card.date !== undefined || card.caption) && (
          <div className="mt-1 flex items-baseline justify-between gap-2 text-3xs text-muted-foreground">
            <span className="truncate">
              {card.date === undefined
                ? ""
                : formatAxisValue(card.date, card.date_only ? "date-only" : "date")}
            </span>
            {card.caption && <span className="shrink-0 tabular-nums">{card.caption}</span>}
          </div>
        )}
      </div>
      {card.progress !== undefined && (
        <div className="h-0.5 w-full bg-muted">
          <div
            className="h-full"
            style={{
              width: `${Math.max(0, Math.min(1, card.progress)) * 100}%`,
              backgroundColor: toneColor("accent"),
            }}
          />
        </div>
      )}
    </article>
  );
}
