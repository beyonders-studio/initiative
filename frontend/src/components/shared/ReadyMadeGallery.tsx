import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** One ready-made thing to start from: its name, what it is for, and a
 *  glimpse of what it brings. */
export type ReadyMadeEntry = {
  key: string;
  name: string;
  hint: string;
  /** Drawn before its name. */
  icon?: ReactNode;
  /** Beside its name, muted: that the place already has one by this name. */
  note?: string;
  /** Under its hint: what it brings, in a line or two. */
  brings?: ReactNode;
};

export type ReadyMadeGroup = { key: string; name: string; entries: ReadyMadeEntry[] };

/**
 * Where a new thing starts: blank, or one of the ready-made ones, grouped by
 * what they are for. Each is a button pressed to choose it; the one chosen is
 * marked. What is chosen is the caller's, as is any other place to start
 * from, which it draws under these.
 */
export const ReadyMadeGallery = ({
  blank,
  groups,
  loading = false,
  chosen,
  onChoose,
}: {
  /** What starting blank is called, and what it gives. */
  blank: { name: string; hint: string };
  groups: ReadyMadeGroup[];
  loading?: boolean;
  /** The entry chosen, by its key; `null` for blank, and `undefined` where
   *  the start chosen is another of the caller's. */
  chosen: string | null | undefined;
  onChoose: (entry: ReadyMadeEntry | null) => void;
}) => (
  <>
    <button
      type="button"
      aria-pressed={chosen === null}
      onClick={() => onChoose(null)}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-left",
        chosen === null ? "border-primary bg-primary/10" : "hover:bg-muted"
      )}
    >
      <span className="block font-medium text-sm">{blank.name}</span>
      <span className="block text-muted-foreground text-xs">{blank.hint}</span>
    </button>

    {loading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
    {groups.map((group) => (
      <section key={group.key} className="space-y-2">
        <h3 className="font-semibold text-muted-foreground text-xs uppercase">{group.name}</h3>
        <div className="grid grid-cols-fill-56/2 gap-2">
          {group.entries.map((entry) => (
            <button
              key={entry.key}
              type="button"
              aria-pressed={chosen === entry.key}
              onClick={() => onChoose(entry)}
              className={cn(
                "flex items-start gap-2 rounded-md border px-3 py-2 text-left",
                chosen === entry.key ? "border-primary bg-primary/10" : "hover:bg-muted"
              )}
            >
              {entry.icon}
              <span className="min-w-0">
                <span className="block font-medium text-sm">
                  {entry.name}
                  {entry.note ? (
                    <span className="ml-1 font-normal text-muted-foreground text-xs">
                      {entry.note}
                    </span>
                  ) : null}
                </span>
                <span className="block text-muted-foreground text-xs">{entry.hint}</span>
                {entry.brings ? (
                  <span className="block text-muted-foreground text-xs">{entry.brings}</span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      </section>
    ))}
  </>
);
