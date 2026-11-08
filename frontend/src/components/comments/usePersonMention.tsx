import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { type MentionChoice, MentionPopover } from "@/components/comments/MentionPopover";
import type { MemberSearchScope } from "@/hooks/useUsers";
import { getCaretCoordinates } from "@/lib/caretCoordinates";
import { type ActiveMention, activeMention } from "@/lib/mentions";

// Matches the popover's width (w-64), so it can be kept inside the field.
const POPOVER_WIDTH = 256;

/** How long the list survives a blur, so a click on it lands. */
const BLUR_GRACE_MS = 200;

type Field = HTMLTextAreaElement | HTMLInputElement;

/** The `@name` being typed, and where in the field it starts. */
type Typing = ActiveMention & { start: number };

/**
 * The member list under a half-typed `@` in a plain one-line field, such as a
 * new task's title. Picking somebody writes their handle, `@name`, where the
 * `@` was, for whatever reads the field to find.
 *
 * Spread `handlers` on the field and call `sync` from its change handler with
 * the new text. While the list is open it owns the arrow keys, Enter, Tab and
 * Escape; `open` says when, so a caller can keep its own keys out of the way.
 */
export const usePersonMention = ({
  field,
  text,
  onChange,
  members,
  enabled,
  onPick,
}: {
  field: { current: Field | null };
  text: string;
  onChange: (next: string) => void;
  /** Whose people the list offers. */
  members: MemberSearchScope;
  enabled: boolean;
  /** Told who was picked, as the field gains their handle. */
  onPick?: (member: UserSummary) => void;
}): {
  open: boolean;
  sync: (element: Field, value?: string) => void;
  handlers: { onSelect: (event: { currentTarget: Field }) => void; onBlur: () => void };
  popover: ReactNode;
} => {
  const [typing, setTyping] = useState<Typing | null>(null);
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const blurTimer = useRef<number>(undefined);
  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

  const sync = useCallback(
    (element: Field, value: string = element.value) => {
      const caret = element.selectionStart ?? value.length;
      const active = enabled ? activeMention(value.slice(0, caret)) : null;
      if (!active?.user) {
        setTyping(null);
        return;
      }
      const start = caret - active.length;
      const at = getCaretCoordinates(element, start);
      setTyping({ ...active, start });
      setAnchor({
        top: at.top + at.height + 4,
        left: Math.min(at.left, Math.max(0, element.offsetWidth - POPOVER_WIDTH)),
      });
    },
    [enabled]
  );

  const pick = (choice: MentionChoice) => {
    if (!typing || !choice.user) return;
    const before = text.slice(0, typing.start);
    const written = `@${choice.member.username}`;
    const after = text.slice(typing.start + typing.length).replace(/^\s*/, " ");
    setTyping(null);
    onPick?.(choice.member);
    onChange(before + written + after);
    const caret = before.length + written.length + 1;
    setTimeout(() => {
      field.current?.focus();
      field.current?.setSelectionRange(caret, caret);
    }, 0);
  };

  return {
    open: typing !== null,
    sync,
    handlers: {
      onSelect: (event) => sync(event.currentTarget),
      onBlur: () => {
        window.clearTimeout(blurTimer.current);
        blurTimer.current = window.setTimeout(() => setTyping(null), BLUR_GRACE_MS);
      },
    },
    popover: typing ? (
      <MentionPopover
        active={typing}
        initiativeId={0}
        members={members}
        anchor={anchor}
        onSelect={pick}
        onClose={() => setTyping(null)}
      />
    ) : null,
  };
};
