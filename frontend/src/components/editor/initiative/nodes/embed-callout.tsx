import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { $getNodeByKey, type NodeKey } from "lexical";
import type { LucideIcon } from "lucide-react";
import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { EmbedSettingsButton } from "@/components/editor/initiative/nodes/embed-settings-button";
import { $isReferenceEmbedNode } from "@/components/editor/initiative/nodes/reference-embed-node";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

/**
 * Whether an embed is folded, and the fold.
 *
 * Folded is saved with the page, as a callout's is. A reader who cannot edit
 * the page folds it for themselves; the page's own answer returns when they
 * reload, or when somebody who can changes it.
 */
export function useEmbedFold(nodeKey: NodeKey, collapsed: boolean) {
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const [readerFolded, setReaderFolded] = useState<boolean | null>(null);
  const folded = editable ? collapsed : (readerFolded ?? collapsed);
  const toggle = () => {
    if (!editable) {
      setReaderFolded(!folded);
      return;
    }
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isReferenceEmbedNode(node)) node.setCollapsed(!folded);
    });
  };
  return { folded, toggle };
}

/**
 * The callout every embed draws in: its mark, its title and a word on what it
 * is, the embed's own buttons — settings where the page can be edited, then
 * any the caller adds, then the fold where there is anything to fold — and
 * below them what it shows.
 */
export function EmbedCallout({
  icon: Icon,
  title,
  meta,
  nodeKey,
  actions,
  fold,
  children,
}: {
  icon: LucideIcon;
  title: ReactNode;
  meta?: ReactNode;
  nodeKey: NodeKey;
  actions?: ReactNode;
  fold?: { folded: boolean; toggle: () => void } | null;
  children?: ReactNode;
}) {
  const { t } = useTranslation("editor");
  const editable = useLexicalEditable();
  return (
    <>
      <span className="callout-icon" aria-hidden="true" />
      <div className="callout-body space-y-2">
        <div className="flex items-start gap-2">
          <Icon className="mt-1 size-4 shrink-0 text-muted-foreground" />
          {title}
          {meta ? (
            <span className="shrink-0 pt-0.5 text-muted-foreground text-xs">{meta}</span>
          ) : null}
          {editable ? <EmbedSettingsButton nodeKey={nodeKey} /> : null}
          {actions}
          {fold ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="-my-1 size-7 shrink-0"
              onClick={fold.toggle}
              aria-expanded={!fold.folded}
              aria-label={t(fold.folded ? "embeds.expand" : "embeds.collapse")}
              title={t(fold.folded ? "embeds.expand" : "embeds.collapse")}
            >
              <ChevronDown
                className={cn("size-4 transition-transform", fold.folded && "-rotate-90")}
              />
            </Button>
          ) : null}
        </div>
        {children}
      </div>
    </>
  );
}
