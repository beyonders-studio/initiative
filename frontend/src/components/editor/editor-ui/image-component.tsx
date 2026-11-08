import { AutoFocusPlugin } from "@lexical/react/LexicalAutoFocusPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { LexicalNestedComposer } from "@lexical/react/LexicalNestedComposer";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { useExtensionDependency } from "@lexical/react/useExtensionComponent";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useLexicalNodeSelection } from "@lexical/react/useLexicalNodeSelection";
import { mergeRegister } from "@lexical/utils";
import type { BaseSelection, LexicalCommand, LexicalEditor, NodeKey } from "lexical";
import {
  $getNodeByKey,
  $getSelection,
  $isNodeSelection,
  $isRangeSelection,
  $setSelection,
  CLICK_COMMAND,
  COMMAND_PRIORITY_LOW,
  createCommand,
  DRAGSTART_COMMAND,
  KEY_BACKSPACE_COMMAND,
  KEY_DELETE_COMMAND,
  KEY_ENTER_COMMAND,
  KEY_ESCAPE_COMMAND,
  ParagraphNode,
  RootNode,
  SELECTION_CHANGE_COMMAND,
  TextNode,
} from "lexical";
import { Maximize2, Star } from "lucide-react";
import { type JSX, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  canBeFeatured,
  useFeaturedImage,
} from "@/components/editor/context/featured-image-context";
import { ContentEditable } from "@/components/editor/editor-ui/content-editable";
import { ImageResizer } from "@/components/editor/editor-ui/image-resizer";
import { ImagesExtension } from "@/components/editor/extensions/images-extension";
import { $isImageNode } from "@/components/editor/nodes/image-node";
// import brokenImage from '@/components/editor/images/image-broken.svg';
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { useImageLightbox } from "@/ui/lightbox";

const imageCache = new Set();

/** Tags the caption editor's update that shows a caption from the node, so it
 *  is not written back onto the node as an edit. */
const CAPTION_FROM_NODE = "caption-from-node";

export const RIGHT_CLICK_IMAGE_COMMAND: LexicalCommand<MouseEvent> = createCommand(
  "RIGHT_CLICK_IMAGE_COMMAND"
);

function useSuspenseImage(src: string) {
  if (!imageCache.has(src)) {
    throw new Promise((resolve) => {
      const img = new Image();
      img.src = src;
      img.onload = () => {
        imageCache.add(src);
        resolve(null);
      };
      img.onerror = () => {
        imageCache.add(src);
      };
    });
  }
}

function LazyImage({
  altText,
  className,
  imageRef,
  src,
  width,
  onError,
}: {
  altText: string;
  className: string | null;
  imageRef: { current: null | HTMLImageElement };
  src: string;
  width: "inherit" | number;
  onError: () => void;
}): JSX.Element {
  useSuspenseImage(src);
  return (
    <img
      className={className || undefined}
      src={src}
      alt={altText}
      ref={imageRef}
      style={{
        width,
        height: "auto",
      }}
      onError={onError}
      draggable="false"
      // Inline document images can resolve to an authenticated ``/uploads/`` URL
      // (which carries a token query param on native); keep that out of Referer.
      referrerPolicy="no-referrer"
    />
  );
}

function BrokenImage(): JSX.Element {
  return (
    <img
      src={""}
      style={{
        height: 200,
        opacity: 0.2,
        width: 200,
      }}
      draggable="false"
      alt="Broken"
    />
  );
}

export default function ImageComponent({
  src,
  altText,
  nodeKey,
  width,
  resizable,
  showCaption,
  caption,
  captionState,
  captionsEnabled,
}: {
  altText: string;
  caption: LexicalEditor;
  captionState: string;
  nodeKey: NodeKey;
  resizable: boolean;
  showCaption: boolean;
  src: string;
  width: "inherit" | number;
  captionsEnabled: boolean;
}): JSX.Element {
  const resolvedSrc = useExtensionDependency(ImagesExtension).config.resolveSrc(src);
  const imageRef = useRef<null | HTMLImageElement>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [isSelected, setSelected, clearSelection] = useLexicalNodeSelection(nodeKey);
  const [isResizing, setIsResizing] = useState<boolean>(false);
  // const { isCollabActive } = useCollaborationContext();
  const [editor] = useLexicalComposerContext();
  const [selection, setSelection] = useState<BaseSelection | null>(null);
  const activeEditorRef = useRef<LexicalEditor | null>(null);
  const [isLoadError, setIsLoadError] = useState<boolean>(false);
  const isEditable = useLexicalEditable();
  const { t } = useTranslation(["editor", "common"]);
  // A picture opens full size, paging with the others in the document. Being
  // read, a click opens it; being written, a click selects it to resize, so it
  // opens from a button on the selected picture or a double click instead.
  const lightbox = useImageLightbox();
  const [lightboxTarget, setLightboxTarget] = useState<HTMLDivElement | null>(null);
  const opensFullSize = lightbox !== null && !isLoadError;
  useEffect(
    () =>
      lightbox && lightboxTarget && !isLoadError
        ? lightbox.register(lightboxTarget, { src: resolvedSrc, alt: altText })
        : undefined,
    [lightbox, lightboxTarget, isLoadError, resolvedSrc, altText]
  );
  const openFullSize = () => {
    if (lightboxTarget) lightbox?.open(lightboxTarget);
  };
  const openLabel = altText
    ? t("common:lightbox.openNamed", { name: altText })
    : t("common:lightbox.open");
  const featured = useFeaturedImage();
  // The caption last shown or written from here, so the echo of an edit is
  // not shown again over what has been typed since.
  const shownCaptionRef = useRef<string | null>(null);

  // The caption is the node's `captionState`, and this editor shows it: one
  // written elsewhere (another collaborator, a node made by collaboration)
  // arrives as a new value.
  useEffect(() => {
    if (!captionState || captionState === shownCaptionRef.current) return;
    shownCaptionRef.current = captionState;
    if (captionState === JSON.stringify(caption.getEditorState().toJSON())) return;
    const next = caption.parseEditorState(captionState);
    // A caption nobody wrote is stored as a root with nothing in it, which
    // Lexical refuses as a state. The caption editor starts out showing that.
    if (next.isEmpty()) return;
    caption.setEditorState(next, { tag: CAPTION_FROM_NODE });
  }, [caption, captionState]);

  // What is typed into the caption is written onto the node, which is what
  // collaboration carries and the document saves.
  useEffect(
    () =>
      caption.registerUpdateListener(({ editorState, tags, dirtyElements, dirtyLeaves }) => {
        if (tags.has(CAPTION_FROM_NODE) || (dirtyElements.size === 0 && dirtyLeaves.size === 0)) {
          return;
        }
        const next = JSON.stringify(editorState.toJSON());
        shownCaptionRef.current = next;
        editor.update(() => {
          const node = $getNodeByKey(nodeKey);
          if ($isImageNode(node) && node.getCaptionState() !== next) node.setCaptionState(next);
        });
      }),
    [caption, editor, nodeKey]
  );

  const $onDelete = useCallback(
    (payload: KeyboardEvent) => {
      const deleteSelection = $getSelection();
      if (isSelected && $isNodeSelection(deleteSelection)) {
        const event: KeyboardEvent = payload;
        event.preventDefault();
        editor.update(() => {
          deleteSelection.getNodes().forEach((node) => {
            if ($isImageNode(node)) {
              node.remove();
            }
          });
        });
      }
      return false;
    },
    [editor, isSelected]
  );

  const $onEnter = useCallback(
    (event: KeyboardEvent | null) => {
      const latestSelection = $getSelection();
      const buttonElem = buttonRef.current;
      if (
        isSelected &&
        $isNodeSelection(latestSelection) &&
        latestSelection.getNodes().length === 1
      ) {
        if (showCaption) {
          // Move focus into nested editor
          $setSelection(null);
          event?.preventDefault();
          caption.focus();
          return true;
        } else if (buttonElem !== null && buttonElem !== document.activeElement) {
          event?.preventDefault();
          buttonElem.focus();
          return true;
        }
      }
      return false;
    },
    [caption, isSelected, showCaption]
  );

  const $onEscape = useCallback(
    (event: KeyboardEvent) => {
      if (activeEditorRef.current === caption || buttonRef.current === event.target) {
        $setSelection(null);
        editor.update(() => {
          setSelected(true);
          const parentRootElement = editor.getRootElement();
          if (parentRootElement !== null) {
            parentRootElement.focus();
          }
        });
        return true;
      }
      return false;
    },
    [caption, editor, setSelected]
  );

  const onClick = useCallback(
    (payload: MouseEvent) => {
      const event = payload;

      if (isResizing) {
        return true;
      }
      if (event.target === imageRef.current) {
        if (event.shiftKey) {
          setSelected(!isSelected);
        } else {
          clearSelection();
          setSelected(true);
        }
        return true;
      }

      return false;
    },
    [isResizing, isSelected, setSelected, clearSelection]
  );

  const onRightClick = useCallback(
    (event: MouseEvent): void => {
      editor.getEditorState().read(() => {
        const latestSelection = $getSelection();
        const domElement = event.target as HTMLElement;
        if (
          domElement.tagName === "IMG" &&
          $isRangeSelection(latestSelection) &&
          latestSelection.getNodes().length === 1
        ) {
          editor.dispatchCommand(RIGHT_CLICK_IMAGE_COMMAND, event as MouseEvent);
        }
      });
    },
    [editor]
  );

  useEffect(() => {
    let isMounted = true;
    const rootElement = editor.getRootElement();
    const unregister = mergeRegister(
      editor.registerUpdateListener(({ editorState }) => {
        if (isMounted) {
          setSelection(editorState.read(() => $getSelection()));
        }
      }),
      editor.registerCommand(
        SELECTION_CHANGE_COMMAND,
        (_, activeEditor) => {
          activeEditorRef.current = activeEditor;
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand<MouseEvent>(CLICK_COMMAND, onClick, COMMAND_PRIORITY_LOW),
      editor.registerCommand<MouseEvent>(RIGHT_CLICK_IMAGE_COMMAND, onClick, COMMAND_PRIORITY_LOW),
      editor.registerCommand(
        DRAGSTART_COMMAND,
        (event) => {
          if (event.target === imageRef.current) {
            // TODO This is just a temporary workaround for FF to behave like other browsers.
            // Ideally, this handles drag & drop too (and all browsers).
            event.preventDefault();
            return true;
          }
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand(KEY_DELETE_COMMAND, $onDelete, COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_BACKSPACE_COMMAND, $onDelete, COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_ENTER_COMMAND, $onEnter, COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_ESCAPE_COMMAND, $onEscape, COMMAND_PRIORITY_LOW)
    );

    rootElement?.addEventListener("contextmenu", onRightClick);

    return () => {
      isMounted = false;
      unregister();
      rootElement?.removeEventListener("contextmenu", onRightClick);
    };
  }, [editor, $onDelete, $onEnter, $onEscape, onClick, onRightClick]);

  const setShowCaption = () => {
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isImageNode(node)) {
        node.setShowCaption(true);
      }
    });
  };

  const onResizeEnd = (nextWidth: "inherit" | number, nextHeight: "inherit" | number) => {
    // Delay hiding the resize bars for click case
    setTimeout(() => {
      setIsResizing(false);
    }, 200);

    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isImageNode(node)) {
        node.setWidthAndHeight(nextWidth, nextHeight);
      }
    });
  };

  const onResizeStart = () => {
    setIsResizing(true);
  };

  const draggable = isSelected && $isNodeSelection(selection) && !isResizing;
  const isFocused = (isSelected || isResizing) && isEditable;
  const offersFeatured = featured !== null && isFocused && !isResizing && canBeFeatured(src);
  const isFeatured = featured?.url === src;
  return (
    <Suspense fallback={null}>
      <>
        {/* Being written, a double click is a shortcut to full size; the
            button on the selected picture is the way in. */}
        <div
          ref={setLightboxTarget}
          draggable={draggable}
          onDoubleClick={opensFullSize && isEditable ? openFullSize : undefined}
        >
          {isLoadError ? (
            <BrokenImage />
          ) : opensFullSize && !isEditable ? (
            <button
              type="button"
              aria-label={openLabel}
              onClick={openFullSize}
              className="block max-w-full cursor-zoom-in rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <LazyImage
                className="max-w-full"
                src={resolvedSrc}
                altText={altText}
                imageRef={imageRef}
                width={width}
                onError={() => setIsLoadError(true)}
              />
            </button>
          ) : (
            <LazyImage
              className={`max-w-full cursor-default ${
                isFocused
                  ? `${$isNodeSelection(selection) ? "draggable cursor-grab active:cursor-grabbing" : ""} focused ring-2 ring-primary ring-offset-2`
                  : null
              }`}
              src={resolvedSrc}
              altText={altText}
              imageRef={imageRef}
              width={width}
              onError={() => setIsLoadError(true)}
            />
          )}
        </div>

        {showCaption && (
          <div className="image-caption-container absolute right-0 bottom-1 left-0 m-0 block min-w-[100px] overflow-hidden border-t bg-background/90">
            <LexicalNestedComposer
              initialEditor={caption}
              initialNodes={[RootNode, TextNode, ParagraphNode]}
            >
              <AutoFocusPlugin />
              <HistoryPlugin />
              <RichTextPlugin
                contentEditable={
                  <ContentEditable
                    className="ImageNode__contentEditable user-select-text word-break-break-word relative block min-h-5 w-[calc(100%-20px)] cursor-text resize-none whitespace-pre-wrap border-0 p-2.5 text-sm caret-primary outline-none"
                    placeholderClassName="ImageNode__placeholder text-sm text-muted-foreground overflow-hidden absolute top-2.5 left-2.5 pointer-events-none text-ellipsis user-select-none whitespace-nowrap inline-block"
                    placeholder="Enter a caption..."
                  />
                }
                ErrorBoundary={LexicalErrorBoundary}
              />
            </LexicalNestedComposer>
          </div>
        )}
        {offersFeatured ? (
          <Button
            type="button"
            size="sm"
            variant={isFeatured ? "secondary" : "outline"}
            className="absolute top-1 left-1 h-7 gap-1.5"
            disabled={isFeatured}
            onClick={() => featured?.set(src)}
          >
            <Star className={cn("h-3.5 w-3.5", isFeatured && "fill-current")} aria-hidden />
            {isFeatured ? t("featuredImage.isFeatured") : t("featuredImage.makeFeatured")}
          </Button>
        ) : null}
        {opensFullSize && isFocused && !isResizing ? (
          <Button
            type="button"
            size="icon"
            variant="outline"
            className="absolute top-1 right-1 size-7"
            aria-label={openLabel}
            title={openLabel}
            onClick={openFullSize}
          >
            <Maximize2 className="h-3.5 w-3.5" aria-hidden />
          </Button>
        ) : null}
        {resizable && $isNodeSelection(selection) && isFocused && (
          <ImageResizer
            showCaption={showCaption}
            setShowCaption={setShowCaption}
            editor={editor}
            buttonRef={buttonRef}
            imageRef={imageRef}
            onResizeStart={onResizeStart}
            onResizeEnd={onResizeEnd}
            captionsEnabled={!isLoadError && captionsEnabled}
          />
        )}
      </>
    </Suspense>
  );
}
