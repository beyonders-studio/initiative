import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CollectionFileSummary, TimelineBucket } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";
import type { CollectionCard } from "@/components/files/collections/collectionLists";
import { type VirtualRow, VirtualRows } from "@/components/files/collections/VirtualRows";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { fileRatio, formatDay, groupByDay } from "@/lib/collections";
import { formatPeriod, formatPeriodYear } from "@/lib/formatDate";

interface CollectionTimelineViewProps {
  files: CollectionFileSummary[];
  /** What each file shows under its picture, as the layout says. */
  card?: CollectionCard;
  /** The months files were added in — what the rail is drawn from. */
  buckets: TimelineBucket[];
  onActivate: (file: CollectionFileSummary, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (file: CollectionFileSummary) => boolean;
  /** A month was picked on the rail. */
  onJump: (bucket: TimelineBucket) => void;
}

/** How tall a file stands in a day's row. Files from the same day sit side
 *  by side at this height, each as wide as its shape makes it. */
const ROW_HEIGHT = 176;
const DAY_HEADING = 28;

/**
 * The collection as a record: a row per day files were added on, newest
 * first, and a rail down the side for jumping months.
 *
 * Files added on the same day sit side by side; a new day starts a new row
 * under its date. Which is the view a design round wants — the sequence is
 * the information, and a day's canvases beside each other say what that round
 * looked like.
 */
export const CollectionTimelineView = ({
  files,
  card,
  buckets,
  onActivate,
  selecting = false,
  isSelected,
  onJump,
}: CollectionTimelineViewProps) => {
  const { t } = useTranslation("files");
  const days = useMemo(() => groupByDay(files), [files]);

  const rows = useMemo<VirtualRow[]>(
    () =>
      days.map((group) => ({
        key: group.day,
        // A heading plus however many rows of files the day wraps to.
        estimate: DAY_HEADING + ROW_HEIGHT * Math.ceil(group.items.length / 4),
        render: () => (
          <section aria-label={formatDay(group.day)}>
            <h3 className="pb-2 font-medium text-muted-foreground text-xs uppercase tracking-wide">
              {formatDay(group.day)}
              <span className="ml-2 font-normal normal-case tracking-normal">
                {t("collections.groups.count", { count: group.items.length })}
              </span>
            </h3>
            <div className="flex flex-wrap gap-2">
              {group.items.map((file) => {
                const width = Math.round(ROW_HEIGHT * fileRatio(file));
                return (
                  <div key={file.id} className="max-w-full" style={{ width }}>
                    <CollectionFileTile
                      file={file}
                      fit="shape"
                      onActivate={(options) => onActivate(file, options)}
                      selecting={selecting}
                      selected={isSelected?.(file) ?? false}
                      named={card?.names}
                      className="max-w-full"
                      style={{ height: ROW_HEIGHT, width }}
                    />
                    {card?.render(file)}
                  </div>
                );
              })}
            </div>
          </section>
        ),
      })),
    [days, card, onActivate, selecting, isSelected, t]
  );

  // The month at the top of the view, so the rail marks where the reader is.
  const [activeDay, setActiveDay] = useState<string | null>(null);
  const onFirstVisible = useCallback(
    (index: number) => setActiveDay(days[index]?.day ?? null),
    [days]
  );
  const activePeriod = (activeDay ?? days[0]?.day)?.slice(0, 7) ?? null;

  return (
    <div className="flex gap-3">
      <div className="min-w-0 flex-1">
        <VirtualRows rows={rows} onFirstVisible={onFirstVisible} />
      </div>
      <TimelineRail
        stops={buckets}
        activePeriod={activePeriod}
        onPick={onJump}
        formatLabel={(stop) => formatPeriod(stop.period)}
        formatGroup={(stop) => formatPeriodYear(stop.period)}
        className="sticky top-4 h-[70vh] self-start"
      />
    </div>
  );
};
