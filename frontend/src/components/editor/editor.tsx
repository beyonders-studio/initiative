"use client";

import { LexicalCollaboration } from "@lexical/react/LexicalCollaborationContext";
import { CollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import type { Provider } from "@lexical/yjs";
import type { AnyLexicalExtension, EditorState, SerializedEditorState } from "lexical";
import { Loader2 } from "lucide-react";
import { type ComponentProps, useMemo, useRef } from "react";
import type * as Y from "yjs";

import { DocumentOutlineTracker } from "@/components/editor/DocumentOutline";
import { COLLAB_EXCLUDED_PROPERTIES } from "@/components/editor/nodes/image-node";
import type { EditorVariant } from "@/components/editor/variant";
import { cn } from "@/ui/lib/utils";
import { ImageLightboxScope } from "@/ui/lightbox";
import { TooltipProvider } from "@/ui/tooltip";

import { documentExtension } from "./document-extension";
import { Plugins } from "./plugins";

/** A document shared live through Yjs, which then owns its history and its
 *  content. */
export interface EditorCollaboration {
  providerFactory: (id: string, yjsDocMap: Map<string, Y.Doc>) => Provider;
  /** Who is writing, as the others see their caret. */
  username: string;
  cursorColor: string;
  /** Whether this body has synced with its room at least once. The syncing
   *  cover waits for that and no longer: a reconnect after it leaves the
   *  document in place. */
  hasSynced: boolean;
}

export interface EditorProps
  extends Pick<
    ComponentProps<typeof Plugins>,
    "plugins" | "pickerOptions" | "insertActions" | "selectionActions"
  > {
  editorState?: EditorState;
  editorSerializedState?: SerializedEditorState;
  onChange?: (editorState: EditorState) => void;
  onSerializedChange?: (editorSerializedState: SerializedEditorState) => void;
  readOnly?: boolean;
  showToolbar?: boolean;
  className?: string;
  collaboration?: EditorCollaboration | null;
  trackChanges?: boolean;
  /** Which surface this editor is on. `post` narrows the toolbar to what
   *  writing a notice needs — see `EditorVariant`. */
  variant?: EditorVariant;
  /** Characters the body may hold, shown as a remaining count. */
  maxLength?: number;
  /** The container already supplies the horizontal gutter — see `Plugins.compact`. */
  compact?: boolean;
  /** The host's own nodes and behaviours, read when the editor is made. */
  extension?: AnyLexicalExtension;
}

export function Editor({
  editorState,
  editorSerializedState,
  onChange,
  onSerializedChange,
  readOnly = false,
  showToolbar = true,
  className,
  collaboration = null,
  trackChanges,
  variant = "document",
  maxLength,
  compact = false,
  extension,
  plugins,
  pickerOptions,
  insertActions,
  selectionActions,
}: EditorProps) {
  const cursorsContainerRef = useRef<HTMLDivElement>(null!);

  const useCollaborativeMode = collaboration !== null;

  const showSyncingOverlay = collaboration !== null && !collaboration.hasSynced;

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
  const initialExtensionRef = useRef(extension);

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
        extension: initialExtensionRef.current,
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
      {/* Above the composer, which portals its decorators in itself, so that
          every picture is inside it: being read, they open full size and page
          through the document's others. */}
      <ImageLightboxScope>
        <LexicalExtensionComposer extension={appExtension} contentEditable={null}>
          <TooltipProvider>
            <Plugins
              showToolbar={showToolbar}
              readOnly={readOnly}
              collaborative={useCollaborativeMode}
              cursorsContainerRef={cursorsContainerRef}
              variant={variant}
              maxLength={maxLength}
              compact={compact}
              plugins={plugins}
              pickerOptions={pickerOptions}
              insertActions={insertActions}
              selectionActions={selectionActions}
            />

            {/* Publishes the headings to a `DocumentOutlineScope`, where the
              page's contents list reads them. Inert without one. */}
            <DocumentOutlineTracker />

            {collaboration && (
              <LexicalCollaboration>
                {/* The server makes a document's Yjs state from its saved
                    content before anyone joins, so the room always arrives
                    holding the document and no tab fills it. */}
                <CollaborationPlugin
                  id="main"
                  providerFactory={collaboration.providerFactory}
                  shouldBootstrap={false}
                  username={collaboration.username}
                  cursorColor={collaboration.cursorColor}
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
    </div>
  );
}
