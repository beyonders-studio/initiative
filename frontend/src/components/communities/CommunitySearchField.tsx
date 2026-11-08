/**
 * The community directory's search box, wherever the directory shows one.
 *
 * The sidebar holds it on a wide screen. Below `lg` the sidebar is off-canvas,
 * so the page holds it instead, above the cards it narrows. Both mount this,
 * rather than each keeping a box of its own, so there is one debounce and one
 * place the address is written from and the two can never disagree about what
 * is being searched.
 *
 * The search lives in the URL: this writes it and the page reads it, which is
 * how components on opposite sides of the layout agree without a provider
 * strung between them, and it leaves a filtered directory linkable and
 * reload-proof besides. Typing is debounced before it reaches the URL, and
 * lands with `replace`, so a search is one history entry rather than one per
 * keystroke.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/** Long enough that a pause reads as "done typing", short enough that results
 *  arrive while the reader is still looking at the box. */
const TYPING_SETTLES_MS = 250;

export const CommunitySearchField = ({ className }: { className?: string }) => {
  const { t } = useTranslation(["communities", "common"]);
  const navigate = useNavigate();
  // Read loosely rather than through the route: one of the places this renders
  // is the app shell, which is mounted above the route that declares the param.
  const search = useSearch({ strict: false }) as { q?: unknown };
  const committed = typeof search.q === "string" ? search.q : "";

  // The box is answerable to the keystroke; the URL is answerable to the pause.
  const [draft, setDraft] = useState(committed);
  const settled = useDebouncedValue(draft, TYPING_SETTLES_MS);
  // The last search this box put in the address. Anything else the address says
  // came from somewhere the box does not know about — the back button, a link
  // into the directory, a restored tab, the other copy of this box — and the
  // address wins there: it is what the page is already showing, and typing must
  // not undo a move the reader made.
  const ours = useRef(committed);

  useEffect(() => {
    if (committed === ours.current) return;
    ours.current = committed;
    setDraft(committed);
  }, [committed]);

  useEffect(() => {
    if (settled === ours.current) return;
    ours.current = settled;
    void navigate({
      to: "/communities",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        q: settled.trim() ? settled : undefined,
      }),
      replace: true,
    });
  }, [settled, navigate]);

  return (
    <Input
      className={className}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      placeholder={t("communities:community.searchPlaceholder")}
      aria-label={t("communities:community.searchPlaceholder")}
    />
  );
};
