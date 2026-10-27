import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { FileSummary } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";
import { type VirtualRow, VirtualRows } from "@/components/files/collections/VirtualRows";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import {
  FILE_TILE_RATIO,
  formatDay,
  groupByDay,
  type MonthStop,
  monthStops,
} from "@/lib/collections";
import { formatPeriod, formatPeriodYear } from "@/lib/formatDate";

interface CollectionTimelineViewProps {
  files: FileSummary[];
  onActivate: (file: FileSummary, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (file: FileSummary) => boolean;
}

/** How tall a file stands in a day's row. Files from the same day sit side
 *  by side at this height. */
const ROW_HEIGHT = 176;
const DAY_HEADING = 28;

/**
 * The collection as a record: a row per day each file arrived on, newest
 * first, and a rail down the side for jumping months.
 *
 * Files that arrived on the same day sit side by side; a new day starts a new
 * row under its date. Which is the view a design round wants — the sequence
 * is the information, and a day's canvases beside each other say what that
 * round looked like. The rail marks the months of the files loaded so far,
 * and the wall loads more as it is scrolled.
 */
export const CollectionTimelineView = ({
  files,
  onActivate,
  selecting = false,
  isSelected,
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
              {group.items.map((file) => (
                <CollectionFileTile
                  key={file.id}
                  file={file}
                  fit="shape"
                  onActivate={(options) => onActivate(file, options)}
                  selecting={selecting}
                  selected={isSelected?.(file) ?? false}
                  className="max-w-full"
                  style={{
                    height: ROW_HEIGHT,
                    width: Math.round(ROW_HEIGHT * FILE_TILE_RATIO),
                  }}
                />
              ))}
            </div>
          </section>
        ),
      })),
    [days, onActivate, selecting, isSelected, t]
  );

  // The month at the top of the view, so the rail marks where the reader is.
  const [activeDay, setActiveDay] = useState<string | null>(null);
  const onFirstVisible = useCallback(
    (index: number) => setActiveDay(days[index]?.day ?? null),
    [days]
  );
  const activePeriod = (activeDay ?? days[0]?.day)?.slice(0, 7) ?? null;

  // The rail is the months of the days loaded; picking one brings its first
  // day to the top.
  const stops = useMemo(() => monthStops(days), [days]);
  const [jump, setJump] = useState<{ index: number } | null>(null);
  const onPick = useCallback(
    (stop: MonthStop) => {
      const index = days.findIndex((group) => group.day.startsWith(stop.period));
      if (index >= 0) setJump({ index });
    },
    [days]
  );

  return (
    <div className="flex gap-3">
      <div className="min-w-0 flex-1">
        <VirtualRows rows={rows} onFirstVisible={onFirstVisible} jump={jump} />
      </div>
      <TimelineRail
        stops={stops}
        activePeriod={activePeriod}
        onPick={onPick}
        formatLabel={(stop) => formatPeriod(stop.period)}
        formatGroup={(stop) => formatPeriodYear(stop.period)}
        className="sticky top-4 h-[70vh] self-start"
      />
    </div>
  );
};
