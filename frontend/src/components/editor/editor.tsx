import { PanelTop, RectangleEllipsis } from "lucide-react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import type * as Y from "yjs";

import { writeWithAi } from "@/api/generated/ai/ai";
import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { EditorInitiativeContext } from "@/components/editor/context/editor-initiative-context";
import { InitiativeExtension } from "@/components/editor/initiative-extension";
import { AIWritingMenu, AIWritingPlugin } from "@/components/editor/plugins/ai-writing-plugin";
import { EntityMentionsPlugin } from "@/components/editor/plugins/entity-mentions-plugin";
import { LazyEmbedDialog } from "@/components/editor/plugins/lazy-embed-dialog";
import { MentionsPlugin } from "@/components/editor/plugins/mentions-plugin";
import { ContinueWritingPickerPlugin } from "@/components/editor/plugins/picker/continue-writing-picker-plugin";
import {
  EmbedPickerPlugin,
  SmartChipPickerPlugins,
} from "@/components/editor/plugins/picker/smart-chip-picker-plugin";
import { SmartChipInsertDialog } from "@/components/editor/plugins/smart-chip-insert-dialog";
import { WikilinksPlugin } from "@/components/editor/plugins/wikilinks-plugin";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useSelfInCommunity } from "@/hooks/useCommunities";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";
import { Editor as CoreEditor, type EditorProps as CoreEditorProps } from "@/ui/editor/editor";
import type { InsertAction } from "@/ui/editor/plugins/toolbar/toolbar-actions";
import { getUserColorHsl } from "@/ui/lib/userColor";

export interface EditorProps
  extends Omit<
    CoreEditorProps,
    | "collaboration"
    | "extension"
    | "plugins"
    | "pickerOptions"
    | "insertActions"
    | "selectionActions"
  > {
  collaborative?: boolean;
  providerFactory?: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  /** Whether this body has synced with its room at least once — see
   *  `EditorCollaboration.hasSynced`. */
  hasSynced?: boolean;
  initiativeId?: number | null;
  /** What is being written, as a reference (`file:12`). Neither trigger
   *  offers it: a page does not point at itself, and a link to it would open
   *  the page the words are already on. Absent while it does not exist yet,
   *  which is a thing nothing can point at anyway. */
  subject?: string | null;
  /** Whether this is a standard document — prose with a caret. `#` is offered
   *  only here: a whiteboard and a spreadsheet are not written into, and a file
   *  or a linked page has no body of its own to write in. */
  supportsEntityMentions?: boolean;
  onWikilinkNavigate?: (fileId: number) => void;
  onCreateReferencedThing?: (
    name: string,
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void
  ) => void;
}

/**
 * Initiative's document editor: the core with Initiative's extension, and
 * what goes with it on the page — references, chips and embeds from the
 * page's initiative, @-mentions, writing help and live collaboration.
 */
export function Editor({
  readOnly = false,
  collaborative = false,
  providerFactory,
  hasSynced = true,
  initiativeId = null,
  subject,
  supportsEntityMentions = false,
  onWikilinkNavigate,
  onCreateReferencedThing,
  ...props
}: EditorProps) {
  const { t } = useTranslation("editor");
  const user = useSelfInCommunity();
  const cursorColor = useRef(user ? getUserColorHsl(user.id) : "hsl(0, 0%, 70%)");
  const communityId = useActiveCommunityId();
  const { isEnabled: aiEnabled } = useAIEnabled();
  // Writing help is for writing: offered where AI is on and the body is editable.
  const aiWriting = aiEnabled && !readOnly && communityId > 0;

  const insertActions: InsertAction[] = supportsEntityMentions
    ? [
        {
          id: "smart-chip",
          label: t("smartChips.insert"),
          icon: <RectangleEllipsis className="size-4" />,
          run: (editor, showModal) =>
            showModal(t("smartChips.insert"), (onClose) => (
              <SmartChipInsertDialog
                initiativeId={initiativeId}
                activeEditor={editor}
                onClose={onClose}
              />
            )),
        },
        // A thing shown in full, or the tasks a filter matches — what `![[ ]]`
        // and the `/` menu's Embed make, for whoever reaches for the toolbar.
        {
          id: "reference-embed",
          label: t("embeds.insert"),
          icon: <PanelTop className="size-4" />,
          run: (editor, showModal) =>
            showModal(t("embeds.insert"), (onClose) => (
              <LazyEmbedDialog activeEditor={editor} onClose={onClose} />
            )),
        },
      ]
    : [];

  return (
    // Outside the composer on purpose: embeds render as Lexical decorators,
    // which the composer portals in itself. Only something above it is an
    // ancestor of all of them.
    <EditorInitiativeContext.Provider value={initiativeId}>
      <CoreEditor
        {...props}
        readOnly={readOnly}
        extension={InitiativeExtension}
        collaboration={
          collaborative && providerFactory
            ? {
                providerFactory,
                username: getUserDisplayName(user, "Anonymous"),
                cursorColor: cursorColor.current,
                hasSynced,
              }
            : null
        }
        plugins={(anchorElem) => (
          <>
            {!readOnly && <MentionsPlugin initiativeId={initiativeId ?? undefined} />}
            {supportsEntityMentions && !readOnly && (
              <EntityMentionsPlugin initiativeId={initiativeId} subject={subject} />
            )}
            <WikilinksPlugin
              initiativeId={initiativeId}
              subject={subject}
              onNavigate={onWikilinkNavigate}
              onCreateThing={onCreateReferencedThing}
            />
            {aiWriting && (
              <AIWritingPlugin
                anchorElem={anchorElem}
                write={(body) => (options, signal) =>
                  writeWithAi(communityId, body, options, signal)
                }
              />
            )}
          </>
        )}
        pickerOptions={[
          // Live chips, offered where `#` is: prose only.
          ...(supportsEntityMentions
            ? [...SmartChipPickerPlugins(t, initiativeId), EmbedPickerPlugin(t)]
            : []),
          ...(aiWriting ? [ContinueWritingPickerPlugin(t)] : []),
        ]}
        insertActions={insertActions}
        selectionActions={aiWriting ? <AIWritingMenu /> : null}
      />
    </EditorInitiativeContext.Provider>
  );
}
