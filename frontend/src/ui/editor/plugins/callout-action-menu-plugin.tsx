import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $findMatchingParent } from "@lexical/utils";
import {
  $getNearestNodeFromDOMNode,
  $getNodeByKey,
  $getSelection,
  $isRangeSelection,
  type NodeKey,
} from "lexical";
import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import {
  $isCalloutNode,
  CALLOUT_VARIANTS,
  type CalloutVariant,
} from "@/ui/editor/nodes/callout-node";
import { CalloutIcon } from "@/ui/editor/plugins/callout-icon";

interface Anchor {
  key: NodeKey;
  top: number;
  left: number;
  size: number;
}

/** How far the button reaches past the icon it sits over, so the hover mark
 * has room around the glyph. */
const PAD = 4;

/**
 * A callout's icon is its menu: change its kind, or take the callout away and
 * keep what it says.
 *
 * A button sits over the icon of the callout the caret is in, so the menu is
 * reachable from the keyboard; a click on any other callout's icon moves it
 * there and opens it.
 */
function CalloutActionMenu({ anchorElem }: { anchorElem: HTMLElement }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [open, setOpen] = useState(false);
  const openRef = useRef(open);
  openRef.current = open;

  const anchorAt = useCallback(
    (key: NodeKey | null): Anchor | null => {
      const icon = key
        ? editor.getElementByKey(key)?.querySelector<HTMLElement>(":scope > .callout-icon")
        : null;
      if (!key || !icon) return null;
      const rect = icon.getBoundingClientRect();
      const host = anchorElem.getBoundingClientRect();
      return {
        key,
        top: rect.top - host.top - PAD,
        left: rect.left - host.left - PAD,
        size: rect.width + PAD * 2,
      };
    },
    [editor, anchorElem]
  );

  const followCaret = useCallback(() => {
    // An open menu stays with the callout it was opened on.
    if (openRef.current) return;
    let key: NodeKey | null = null;
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      key = $findMatchingParent(selection.anchor.getNode(), $isCalloutNode)?.getKey() ?? null;
    });
    setAnchor(anchorAt(key));
  }, [editor, anchorAt]);

  useEffect(() => editor.registerUpdateListener(() => followCaret()), [editor, followCaret]);

  // Closed, the button goes back to the callout the caret is in.
  useEffect(() => {
    if (!open) followCaret();
  }, [open, followCaret]);

  useEffect(
    () =>
      editor.registerRootListener((root, previous) => {
        const onPointerDown = (event: PointerEvent) => {
          const icon = (event.target as HTMLElement | null)?.closest?.(".callout-icon");
          if (!icon || !editor.isEditable()) return;
          let key: NodeKey | null = null;
          editor.read(() => {
            const node = $getNearestNodeFromDOMNode(icon);
            key = $isCalloutNode(node) ? node.getKey() : null;
          });
          // An embed draws the same icon, and has no menu.
          const next = anchorAt(key);
          if (!next) return;
          // Leave the caret where it was; this is a menu, not a place to write.
          event.preventDefault();
          setAnchor(next);
          setOpen(true);
        };
        previous?.removeEventListener("pointerdown", onPointerDown);
        root?.addEventListener("pointerdown", onPointerDown);
        return () => root?.removeEventListener("pointerdown", onPointerDown);
      }),
    [editor, anchorAt]
  );

  const setVariant = (variant: CalloutVariant) => {
    if (!anchor) return;
    editor.update(() => {
      const node = $getNodeByKey(anchor.key);
      if ($isCalloutNode(node)) {
        node.setVariant(variant);
      }
    });
  };

  const remove = () => {
    if (!anchor) return;
    editor.update(() => {
      const node = $getNodeByKey(anchor.key);
      if ($isCalloutNode(node)) {
        for (const child of node.getChildren()) {
          node.insertBefore(child);
        }
        node.remove();
      }
    });
  };

  if (!anchor) {
    return null;
  }
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        className="absolute z-10 cursor-pointer rounded-md hover:bg-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/10"
        style={{ top: anchor.top, left: anchor.left, width: anchor.size, height: anchor.size }}
        aria-label={t("calloutActions")}
      />
      <DropdownMenuContent align="start">
        {CALLOUT_VARIANTS.map((variant) => (
          <DropdownMenuItem key={variant} onSelect={() => setVariant(variant)}>
            <CalloutIcon variant={variant} className="size-4" />
            {t(`calloutKinds.${variant}`)}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={remove}>
          <Trash2 className="size-4" />
          {t("removeCallout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function CalloutActionMenuPlugin({ anchorElem }: { anchorElem: HTMLElement | null }) {
  if (!anchorElem) {
    return null;
  }
  return createPortal(<CalloutActionMenu anchorElem={anchorElem} />, anchorElem);
}
