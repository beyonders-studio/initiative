/**
 * The head of every tool page: a band in the initiative's colour that runs the
 * width of the content area and up under the shell's sticky bar, fading into
 * the page. On it, three rows: the breadcrumb with Settings across from it and
 * nothing else; the name and description; and the tool chest, the strip of
 * what the tool is and what only it has.
 *
 * The breadcrumb names where the page lives and the title names the page, so
 * neither repeats the other. The colour is the initiative's on every tool, so
 * it says which initiative you are in; a tool's own colour or emoji is the
 * `mark` in front of its name.
 */
import { Link } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import { type CSSProperties, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { AskToEdit } from "@/components/access/RequestAccess";
import { BookmarkButton } from "@/components/BookmarkButton";
import { useFullBleed } from "@/components/PageBanner";
import { SubscribeButton } from "@/components/SubscribeButton";
import { ToolBreadcrumb, type ToolBreadcrumbSegment } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useListedInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { hexToRgba, resolveInitiativeColor } from "@/lib/initiativeColors";
import { useFieldDraft } from "@/lib/layouts/editing";
import { cn } from "@/lib/utils";

const TITLE_CLASS = "font-semibold text-3xl tracking-tight";

export interface ToolPageHeaderProps {
  tool: Tool;
  /** The initiative the page belongs to; null for a community-level calendar. */
  initiativeId?: number | null;
  /** Ancestors after the tool-list crumb: a task's project, a setting's entity. */
  trail?: ToolBreadcrumbSegment[];
  /** The page's settings (community-relative), for someone who may change them:
   *  the one thing across from the breadcrumb. Left out on a tool's own page
   *  (`starId`), the reader may only read it, so "Ask to edit" stands there
   *  instead. */
  settingsTo?: string;
  /** Search params the settings link carries (an event's occurrence). */
  settingsSearch?: Record<string, string>;
  /** The entity's own emoji or colour dot, in front of its name. */
  mark?: ReactNode;
  /** The page's title. With `onRename`, the name a person can click to change. */
  title: ReactNode;
  /** Saves a new name; given only to someone who may rename. Resolves once
   *  saved, so the field stays open on a failure. */
  onRename?: (name: string) => Promise<unknown>;
  /** The tool this page is, for the bookmark and the subscribe beside its name. Left
   *  out where the page is something inside a tool (a task) or about one (its
   *  settings). */
  starId?: number;
  /** Beside the title: a status. */
  titleExtras?: ReactNode;
  /** Under the title: the description, a byline. */
  children?: ReactNode;
  /** The tool chest under the name and description. */
  chest?: ReactNode;
}

export const ToolPageHeader = ({
  tool,
  initiativeId,
  trail,
  settingsTo,
  settingsSearch,
  mark,
  title,
  onRename,
  starId,
  titleExtras,
  children,
  chest,
}: ToolPageHeaderProps) => {
  const { t } = useTranslation("common");
  const gp = useCommunityPath();
  const box = useFullBleed<HTMLElement>();
  const color = resolveInitiativeColor(useListedInitiative(initiativeId)?.color);

  return (
    <header
      ref={box.ref}
      style={{
        ...box.style,
        // Up behind the sticky bar, and back down by as much inside, so the
        // colour runs to the top of the page and the words stay put.
        ...(box.header ? { marginTop: -box.header, paddingTop: box.header } : null),
        backgroundImage: `linear-gradient(to bottom, ${hexToRgba(color, 0.28)} 0%, ${hexToRgba(color, 0.12)} 55%, transparent 100%)`,
      }}
      className="-mx-4 -mt-4 md:-mx-8 md:-mt-8"
    >
      <div
        // Lines the copy back up with the page's own column below it.
        style={{ paddingLeft: box.inset.left, paddingRight: box.inset.right }}
        className={cn("space-y-4 px-4 pt-4 md:px-8 md:pt-8", chest ? "pb-4" : "pb-6")}
      >
        {/* The breadcrumb and Settings, and nothing else: one row, always,
            the crumb wrapping inside its own share. */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 pt-1.5">
            <ToolBreadcrumb tool={tool} initiativeId={initiativeId} trail={trail} />
          </div>
          {settingsTo ? (
            <Button asChild variant="outline" size="sm" className="shrink-0">
              <Link to={gp(settingsTo)} search={settingsSearch ?? {}}>
                <Settings className="h-4 w-4" aria-hidden />
                {t("toolSettings.title")}
              </Link>
            </Button>
          ) : starId ? (
            <AskToEdit kind={tool} entityId={starId} />
          ) : null}
        </div>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            {mark}
            {onRename && typeof title === "string" ? (
              <EditableTitle name={title} onRename={onRename} />
            ) : (
              <h1 className={cn("min-w-0 break-words", TITLE_CLASS)}>{title}</h1>
            )}
            {starId ? (
              <div className="flex items-center">
                <BookmarkButton
                  tool={tool}
                  entityId={starId}
                  name={typeof title === "string" ? title : undefined}
                  initiativeId={initiativeId}
                />
                <SubscribeButton kind={tool} entityId={starId} />
              </div>
            ) : null}
            {titleExtras}
          </div>
          {children}
        </div>
      </div>
      {chest ? (
        <div
          // On a phone the chest runs edge to edge and its first segment
          // lines up with the page's column; from `md` up it is a card inside
          // that column.
          style={
            {
              "--inset-l": `${box.inset.left}px`,
              "--inset-r": `${box.inset.right}px`,
            } as CSSProperties
          }
          className={cn(
            "[--chest-gutter-right:var(--inset-r)] [--chest-gutter:var(--inset-l)]",
            "md:pr-(--inset-r) md:pl-(--inset-l)",
            "md:[--chest-gutter-right:0.75rem] md:[--chest-gutter:0.75rem]"
          )}
        >
          {chest}
        </div>
      ) : null}
    </header>
  );
};

/** A heading that turns into a field when clicked, typed into as any field
 *  is ({@link useFieldDraft}): Enter or leaving it saves, Escape puts the
 *  name back, and an emptied name is put back too. */
const EditableTitle = ({
  name,
  onRename,
}: {
  name: string;
  onRename: (name: string) => Promise<unknown>;
}) => {
  const { t } = useTranslation("common");
  const [editing, setEditing] = useState(false);
  // The mutation reports its own error, and the name it had shows again.
  const draft = useFieldDraft(
    name,
    (text) => onRename(text.trim()).catch(() => {}),
    (a, b) => a.trim() === b.trim()
  );
  const done = () => {
    if (!draft.value.trim()) draft.restore();
    setEditing(false);
  };

  if (editing) {
    return (
      <Input
        value={draft.value}
        onChange={(event) => draft.change(event.target.value)}
        aria-label={t("toolHeader.rename")}
        className={cn("h-auto min-w-0 flex-1 md:text-3xl", TITLE_CLASS)}
        autoFocus
        onKeyDown={(event) => {
          if (event.key === "Enter" && !draft.value.trim()) draft.restore();
          draft.keys.onKeyDown(event);
          if (event.key === "Enter" || event.key === "Escape") setEditing(false);
        }}
        onBlur={(event) => {
          if (draft.value.trim()) draft.keys.onBlur(event);
          done();
        }}
      />
    );
  }

  return (
    <h1 className={cn("min-w-0 break-words", TITLE_CLASS)}>
      <button
        type="button"
        title={t("toolHeader.rename")}
        onClick={() => setEditing(true)}
        className="cursor-text rounded-md text-left hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {draft.value}
      </button>
    </h1>
  );
};
