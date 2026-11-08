import {
  Bold,
  Code,
  Heading,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  ListTodo,
  MoreHorizontal,
  Strikethrough,
  TextQuote,
} from "lucide-react";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";

import {
  BULLET_LIST,
  cycleHeading,
  insertLink,
  type MarkdownTransform,
  NUMBERED_LIST,
  QUOTE,
  TASK_LIST,
  toggleCode,
  toggleLinePrefix,
  toggleWrap,
} from "@/lib/markdownEditing";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";
import { useRowCapacity } from "@/ui/overflow-toolbar";

/**
 * The edits a keyboard shortcut reaches, by the key that reaches them.
 *
 * No `k`, which GitHub gives to links: it belongs to the command centre here,
 * and a shortcut that opens the command centre *and* writes a link into the
 * comment you were typing is worse than no shortcut at all.
 */
export const MARKDOWN_SHORTCUTS: Record<string, MarkdownTransform> = {
  b: toggleWrap("**"),
  i: toggleWrap("_"),
  e: toggleCode,
};

// ``navigator.platform`` is deprecated; ``userAgent`` carries enough for a
// keyboard-hint heuristic, and matches the convention the editor toolbar uses.
const IS_APPLE =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);

/** What the shortcut hints call the modifier on this platform. */
const MODIFIER = IS_APPLE ? "⌘" : "Ctrl+";

type ToolbarIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

/**
 * One thing the toolbar can do, as data rather than as a rendered button.
 *
 * It has to be data because the same action is rendered two ways: a button
 * while it fits in the row, a menu entry once it doesn't.
 */
/** One of the ways a toolbar item can be done, offered as a menu. */
export interface ToolbarChoice {
  id: string;
  label: string;
  icon: ToolbarIcon;
  onSelect: () => void;
}

export interface ToolbarItem {
  id: string;
  label: string;
  icon: ToolbarIcon;
  onClick: () => void;
  /** Set when the item is done one of several ways — a picture from the
   *  camera or from the library. The button opens these rather than acting. */
  choices?: ToolbarChoice[];
  /** Appended to the label in the tooltip — a keyboard shortcut, usually. */
  hint?: string;
  /** Opens a new group: a separator goes before it. */
  startsGroup?: boolean;
}

interface FormattingAction {
  id: string;
  /** Key in the `common:markdownEditor` group naming the button. */
  labelKey: string;
  icon: ToolbarIcon;
  transform: MarkdownTransform;
  shortcut?: string;
  startsGroup?: boolean;
}

/**
 * Ordered as GitHub's comment toolbar is, so the muscle memory carries over —
 * and, because the row sheds from the right, ordered by what a writer reaches
 * for most: heading, bold and italic are the last three to go.
 */
const FORMATTING_ACTIONS: FormattingAction[] = [
  { id: "heading", labelKey: "heading", icon: Heading, transform: cycleHeading },
  { id: "bold", labelKey: "bold", icon: Bold, transform: toggleWrap("**"), shortcut: "B" },
  { id: "italic", labelKey: "italic", icon: Italic, transform: toggleWrap("_"), shortcut: "I" },
  {
    id: "strikethrough",
    labelKey: "strikethrough",
    icon: Strikethrough,
    transform: toggleWrap("~~"),
  },
  { id: "quote", labelKey: "quote", icon: TextQuote, transform: toggleLinePrefix(QUOTE) },
  { id: "code", labelKey: "code", icon: Code, transform: toggleCode, shortcut: "E" },
  { id: "link", labelKey: "link", icon: LinkIcon, transform: insertLink },
  {
    id: "bulletedList",
    labelKey: "bulletedList",
    icon: List,
    transform: toggleLinePrefix(BULLET_LIST),
    startsGroup: true,
  },
  {
    id: "numberedList",
    labelKey: "numberedList",
    icon: ListOrdered,
    transform: toggleLinePrefix(NUMBERED_LIST),
  },
  { id: "taskList", labelKey: "taskList", icon: ListTodo, transform: toggleLinePrefix(TASK_LIST) },
];

/** One button in the row. */
const ToolbarButton = ({ item, disabled }: { item: ToolbarItem; disabled: boolean }) => (
  <Button
    type="button"
    variant="ghost"
    size="icon-sm"
    className="text-muted-foreground hover:text-foreground"
    disabled={disabled}
    title={item.hint ? `${item.label} (${item.hint})` : item.label}
    aria-label={item.label}
    // The field keeps the caret it had, so the edit lands where the writer
    // left off rather than at the start of the text.
    onMouseDown={(event) => event.preventDefault()}
    onClick={item.onClick}
  >
    <item.icon className="h-4 w-4" aria-hidden={true} />
  </Button>
);

/** A button in the row that opens its choices rather than acting. */
const ToolbarChoiceButton = ({ item, disabled }: { item: ToolbarItem; disabled: boolean }) => (
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="text-muted-foreground hover:text-foreground"
        disabled={disabled}
        title={item.label}
        aria-label={item.label}
      >
        <item.icon className="h-4 w-4" aria-hidden={true} />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      {item.choices?.map((choice) => (
        <DropdownMenuItem key={choice.id} onSelect={choice.onSelect}>
          <choice.icon className="h-4 w-4" aria-hidden={true} />
          {choice.label}
        </DropdownMenuItem>
      ))}
    </DropdownMenuContent>
  </DropdownMenu>
);

const Divider = () => <span aria-hidden="true" className="mx-1 h-4 w-px shrink-0 bg-border" />;

interface MarkdownToolbarProps {
  onApply: (transform: MarkdownTransform) => void;
  disabled?: boolean;
  className?: string;
  /** A surface's own actions, in a group of their own at the end — what a
   *  comment puts its mention triggers in. */
  tools?: ToolbarItem[];
}

/**
 * The formatting buttons over a markdown field.
 *
 * The row never wraps. As it narrows, the buttons that no longer fit move into
 * a menu at its end rather than pushing the field down the screen, so the same
 * toolbar serves a phone and a wide editor.
 *
 * Every button is a plain `button` rather than a submit control: the composer
 * often sits inside a form, and formatting a word must never post it.
 */
export const MarkdownToolbar = ({
  onApply,
  disabled = false,
  className,
  tools,
}: MarkdownToolbarProps) => {
  const { t } = useTranslation("common");

  const items: ToolbarItem[] = [
    ...FORMATTING_ACTIONS.map((action) => ({
      id: action.id,
      label: t(`markdownEditor.${action.labelKey}` as never) as string,
      icon: action.icon,
      hint: action.shortcut ? `${MODIFIER}${action.shortcut}` : undefined,
      startsGroup: action.startsGroup,
      onClick: () => onApply(action.transform),
    })),
    ...(tools ?? []).map((tool, index) => ({ ...tool, startsGroup: index === 0 })),
  ];

  const { rowRef, fits } = useRowCapacity(items.map((item) => item.id));
  const overflowed = items.slice(fits);

  return (
    <div
      role="toolbar"
      aria-label={t("markdownEditor.toolbar")}
      className={cn("flex min-w-0 items-center justify-end gap-0.5", className)}
    >
      <div
        ref={rowRef}
        className="flex min-w-0 flex-1 items-center justify-end gap-0.5 overflow-hidden"
      >
        {items.map((item, index) => (
          // One element per item, its separator included, so the row's children
          // line up one-to-one with what is being measured.
          <span key={item.id} hidden={index >= fits} className="flex shrink-0 items-center">
            {item.startsGroup && index > 0 && <Divider />}
            {item.choices ? (
              <ToolbarChoiceButton item={item} disabled={disabled} />
            ) : (
              <ToolbarButton item={item} disabled={disabled} />
            )}
          </span>
        ))}
      </div>

      <span hidden={overflowed.length === 0} className="flex shrink-0 items-center">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="text-muted-foreground hover:text-foreground"
              disabled={disabled}
              title={t("markdownEditor.more")}
              aria-label={t("markdownEditor.more")}
              onMouseDown={(event) => event.preventDefault()}
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden={true} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {overflowed.map((item, index) => (
              <div key={item.id}>
                {item.startsGroup && index > 0 && <DropdownMenuSeparator />}
                {item.choices ? (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <item.icon className="h-4 w-4" aria-hidden={true} />
                      {item.label}
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      {item.choices.map((choice) => (
                        <DropdownMenuItem key={choice.id} onSelect={choice.onSelect}>
                          <choice.icon className="h-4 w-4" aria-hidden={true} />
                          {choice.label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                ) : (
                  <DropdownMenuItem onSelect={item.onClick}>
                    <item.icon className="h-4 w-4" aria-hidden={true} />
                    {item.label}
                  </DropdownMenuItem>
                )}
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </span>
    </div>
  );
};
