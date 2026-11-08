"use client";

import { LexicalCollaboration } from "@lexical/react/LexicalCollaborationContext";
import { CollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import type { EditorState, SerializedEditorState } from "lexical";
import { Loader2 } from "lucide-react";
import { useMemo, useRef } from "react";
import type * as Y from "yjs";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { EditorInitiativeContext } from "@/components/editor/context/editor-initiative-context";
import { DocumentOutlineTracker } from "@/components/editor/DocumentOutline";
import { COLLAB_EXCLUDED_PROPERTIES } from "@/components/editor/nodes/image-node";
import type { EditorVariant } from "@/components/editor/variant";
import { ImageLightboxScope } from "@/components/markdown/ProseImage";
import { useSelfInCommunity } from "@/hooks/useCommunities";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";
import { getUserColorHsl } from "@/ui/lib/userColor";
import { cn } from "@/ui/lib/utils";
import { TooltipProvider } from "@/ui/tooltip";

import { documentExtension } from "./document-extension";
import { Plugins } from "./plugins";

export interface EditorProps {
  editorState?: EditorState;
  editorSerializedState?: SerializedEditorState;
  onChange?: (editorState: EditorState) => void;
  onSerializedChange?: (editorSerializedState: SerializedEditorState) => void;
  readOnly?: boolean;
  showToolbar?: boolean;
  className?: string;
  collaborative?: boolean;
  providerFactory?: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  trackChanges?: boolean;
  /** Whether this body has synced with its room at least once. The syncing
   *  cover waits for that and no longer: a reconnect after it leaves the
   *  document in place. */
  hasSynced?: boolean;
  initiativeId?: number | null;
  /** What is being written, as a reference (`file:12`) — see
   *  `Plugins.subject`. Absent while it does not exist yet, which is a thing
   *  nothing can point at anyway. */
  subject?: string | null;
  /** Whether this document is prose — see `Plugins.supportsEntityMentions`. */
  supportsEntityMentions?: boolean;
  /** Which surface this editor is on. `post` narrows the toolbar to what
   *  writing a notice needs — see `EditorVariant`. */
  variant?: EditorVariant;
  /** Characters the body may hold, shown as a remaining count. */
  maxLength?: number;
  /** The container already supplies the horizontal gutter — see `Plugins.compact`. */
  compact?: boolean;
  onWikilinkNavigate?: (fileId: number) => void;
  onCreateReferencedThing?: (
    name: string,
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void
  ) => void;
}

export function Editor({
  editorState,
  editorSerializedState,
  onChange,
  onSerializedChange,
  readOnly = false,
  showToolbar = true,
  className,
  collaborative = false,
  providerFactory,
  trackChanges,
  hasSynced = true,
  initiativeId = null,
  subject,
  supportsEntityMentions = false,
  variant = "document",
  maxLength,
  compact = false,
  onWikilinkNavigate,
  onCreateReferencedThing,
}: EditorProps) {
  const user = useSelfInCommunity();
  const userColor = useRef(user ? getUserColorHsl(user.id) : "hsl(0, 0%, 70%)");
  const userName = getUserDisplayName(user, "Anonymous");
  const cursorsContainerRef = useRef<HTMLDivElement>(null!);

  const useCollaborativeMode = Boolean(collaborative && providerFactory);

  const showSyncingOverlay = useCollaborativeMode && !hasSynced;

  // Capture initial editor configuration at first mount. LexicalExtensionComposer
  // recreates (and disposes) the editor whenever the `extension` prop reference
  // changes, so the AppExtension must be stable across re-renders. Subsequent
  // changes to readOnly are applied via editor.setEditable() inside Plugins;
  // editorState / editorSerializedState are only consulted by $initialEditorState
  // which runs once at editor creation, so refs are sufficient.
  const initialReadOnlyRef = useRef(readOnly);
  const initialCollabRef = useRef(useCollaborativeMode);
  const initialEditorStateRef = useRef(editorState);
  const initialEditorSerializedStateRef = useRef(editorSerializedState);

  const appExtension = useMemo(
    () =>
      documentExtension({
        collaborative: initialCollabRef.current,
        editable: !initialReadOnlyRef.current,
        initialEditorState:
          initialEditorStateRef.current ??
          (initialEditorSerializedStateRef.current
            ? JSON.stringify(initialEditorSerializedStateRef.current)
            : null),
      }),
    []
  );

  return (
    <div
      className={cn(
        "relative scroll-pb-14 overflow-y-auto",
        // A document is a page: it draws itself a sheet to sit on. A post is
        // already inside a card, and a second framed, filled box within one
        // reads as a card inside a card.
        variant === "document" && "rounded-lg border bg-background shadow",
        className
      )}
    >
      {showSyncingOverlay && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Syncing document...</span>
          </div>
        </div>
      )}
      {/* Outside the composer on purpose: embeds render as Lexical
          decorators, which the composer portals in itself. Only something above
          it is an ancestor of all of them. */}
      <EditorInitiativeContext.Provider value={initiativeId ?? null}>
        {/* Above the composer for the same reason: its pictures, being read,
            open full size and page through the document's others. */}
        <ImageLightboxScope>
          <LexicalExtensionComposer extension={appExtension} contentEditable={null}>
            <TooltipProvider>
              <Plugins
                showToolbar={showToolbar}
                readOnly={readOnly}
                collaborative={useCollaborativeMode}
                cursorsContainerRef={cursorsContainerRef}
                initiativeId={initiativeId}
                subject={subject}
                supportsEntityMentions={supportsEntityMentions}
                variant={variant}
                maxLength={maxLength}
                compact={compact}
                onWikilinkNavigate={onWikilinkNavigate}
                onCreateReferencedThing={onCreateReferencedThing}
              />

              {/* Publishes the headings to a `DocumentOutlineScope`, where the
                page's contents list reads them. Inert without one. */}
              <DocumentOutlineTracker />

              {useCollaborativeMode && providerFactory && (
                <LexicalCollaboration>
                  {/* The server makes a document's Yjs state from its saved
                      content before anyone joins, so the room always arrives
                      holding the document and no tab fills it. */}
                  <CollaborationPlugin
                    id="main"
                    providerFactory={providerFactory}
                    shouldBootstrap={false}
                    username={userName}
                    cursorColor={userColor.current}
                    cursorsContainerRef={cursorsContainerRef}
                    excludedProperties={COLLAB_EXCLUDED_PROPERTIES}
                  />
                </LexicalCollaboration>
              )}

              {!readOnly && (trackChanges ?? !useCollaborativeMode) && (
                <OnChangePlugin
                  ignoreSelectionChange={true}
                  onChange={(editorState) => {
                    onChange?.(editorState);
                    onSerializedChange?.(editorState.toJSON());
                  }}
                />
              )}
            </TooltipProvider>
          </LexicalExtensionComposer>
        </ImageLightboxScope>
      </EditorInitiativeContext.Provider>
    </div>
  );
}
