import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { $getNodeByKey, type NodeKey } from "lexical";
import { Check, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  $isStatusNode,
  STATUS_COLORS,
  type StatusColor,
} from "@/components/ui/editor/nodes/status-node";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { CHIP_TONE_CLASSES } from "@/lib/smartChips";
import { cn } from "@/lib/utils";

/** Each colour's hue. The pill is a wash of it with the word in it, the same
 * way a smart chip for a task's status is coloured. */
const HUES: Record<Exclude<StatusColor, "neutral">, string> = {
  blue: "#3b82f6",
  green: "#16a34a",
  yellow: "#ca8a04",
  red: "#dc2626",
  purple: "#9333ea",
};

/** The same pill a smart chip is, so the two sit together in one table. */
const PILL =
  "mx-[0.15em] inline-flex items-center rounded-[0.25em] px-[0.4em] py-[0.15em] align-baseline font-medium text-[0.85em] uppercase tracking-wide";

function pillStyle(color: StatusColor) {
  return color === "neutral"
    ? undefined
    : { backgroundColor: `${HUES[color]}26`, color: HUES[color] };
}

interface StatusPillProps {
  nodeKey: NodeKey;
  text: string;
  color: StatusColor;
}

/** A status on the page. For somebody who may edit, clicking it opens the
 * word and the colour to change; a new, empty one opens that way at once,
 * and one closed with no word is taken away. */
export function StatusPill({ nodeKey, text, color }: StatusPillProps) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const isEditable = useLexicalEditable();
  const [open, setOpen] = useState(() => isEditable && text === "");
  const [draft, setDraft] = useState(text);
  // Held here as well as on the node: a new status has no word yet, and a
  // status with no word is removed, so the colour waits for one.
  const [draftColor, setDraftColor] = useState(color);

  // Closed, the draft is what the node holds.
  if (!open && (draft !== text || draftColor !== color)) {
    setDraft(text);
    setDraftColor(color);
  }

  const update = (nextText: string, nextColor: StatusColor) => {
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if (!$isStatusNode(node)) return;
      if (nextText.trim() === "") {
        node.remove();
      } else {
        node.setStatus(nextText.trim(), nextColor);
      }
    });
  };

  const close = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      update(draft, draftColor);
    }
  };

  const pick = (option: StatusColor) => {
    setDraftColor(option);
    // Shown at once where there is a word to show it on.
    if (draft.trim() !== "") {
      update(draft, option);
    }
  };

  const shown = open ? draftColor : color;

  const pill = (
    <span
      className={cn(PILL, shown === "neutral" && CHIP_TONE_CLASSES.neutral)}
      style={pillStyle(shown)}
    >
      {text || t("statusPlaceholder")}
    </span>
  );

  if (!isEditable) {
    return pill;
  }

  return (
    <Popover open={open} onOpenChange={close}>
      <PopoverTrigger asChild>
        <button type="button" className="cursor-pointer" aria-label={t("editStatus")}>
          {pill}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-64 space-y-3 p-3"
        // Only a click elsewhere, Escape or Enter closes it. Focus moving
        // away is not a reason: the menu a new status was inserted from
        // hands focus back to its own button as it closes, which would shut
        // the editor the moment it opened.
        onFocusOutside={(event) => event.preventDefault()}
      >
        <Input
          autoFocus
          value={draft}
          placeholder={t("statusPlaceholder")}
          aria-label={t("statusText")}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              close(false);
            }
          }}
        />
        <div className="flex flex-wrap gap-1.5">
          {STATUS_COLORS.map((option) => (
            <button
              key={option}
              type="button"
              aria-label={t(`statusColors.${option}`)}
              aria-pressed={option === draftColor}
              onClick={() => pick(option)}
              className={cn(PILL, "mx-0", option === "neutral" && CHIP_TONE_CLASSES.neutral)}
              style={pillStyle(option)}
            >
              {option === draftColor ? <Check className="size-3" /> : null}
              {t(`statusColors.${option}`)}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-destructive"
          onClick={() => {
            setOpen(false);
            update("", color);
          }}
        >
          <Trash2 className="size-4" />
          {t("removeStatus")}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
