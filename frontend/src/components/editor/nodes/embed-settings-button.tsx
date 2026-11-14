import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import type { NodeKey } from "lexical";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LazyEmbedDialog } from "@/components/editor/plugins/lazy-embed-dialog";
import { Button } from "@/ui/button";
import { useEditorModal } from "@/ui/editor/editor-hooks/use-modal";

/** The button that reopens an embed's settings, where the page can be edited. */
export function EmbedSettingsButton({ nodeKey }: { nodeKey: NodeKey }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [modal, showModal] = useEditorModal();
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="-my-1 size-7 shrink-0"
        onClick={() =>
          showModal(t("embeds.settings"), (onClose) => (
            <LazyEmbedDialog activeEditor={editor} nodeKey={nodeKey} onClose={onClose} />
          ))
        }
        aria-label={t("embeds.settings")}
        title={t("embeds.settings")}
      >
        <Settings2 className="size-3.5" />
      </Button>
      {modal}
    </>
  );
}
