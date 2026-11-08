import { $isLinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  NodeContextMenuOption,
  NodeContextMenuPlugin,
  NodeContextMenuSeparator,
} from "@lexical/react/LexicalNodeContextMenuPlugin";
import {
  $createTextNode,
  $getNearestNodeFromDOMNode,
  $getNodeByKey,
  $getSelection,
  $isDecoratorNode,
  $isNodeSelection,
  $isRangeSelection,
  $isTextNode,
  COPY_COMMAND,
  CUT_COMMAND,
  type LexicalNode,
  type NodeKey,
  PASTE_COMMAND,
} from "lexical";
import {
  Clipboard,
  ClipboardType,
  Copy,
  Link2Off,
  Scissors,
  SpellCheck,
  Trash2,
} from "lucide-react";
import type { JSX } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { checkWord, getSuggestions, initSpellCheck, isSpellCheckReady } from "@/lib/spell-check";

interface WordAtCursor {
  word: string;
  startOffset: number;
  endOffset: number;
}

function getWordAtCursor(): WordAtCursor | null {
  const selection = $getSelection();
  if (!$isRangeSelection(selection)) return null;

  const anchor = selection.anchor;
  const node = anchor.getNode();

  if (!$isTextNode(node)) return null;

  const textContent = node.getTextContent();
  const offset = anchor.offset;

  // Find word boundaries
  let start = offset;
  let end = offset;

  // Move start backwards to find word start
  while (start > 0 && /\w/.test(textContent[start - 1])) {
    start--;
  }

  // Move end forward to find word end
  while (end < textContent.length && /\w/.test(textContent[end])) {
    end++;
  }

  if (start === end) return null;

  const word = textContent.slice(start, end);
  // Skip if the word contains numbers or is too short
  if (/\d/.test(word) || word.length < 2) return null;

  return { word, startOffset: start, endOffset: end };
}

// Maximum number of spell suggestions to show
const MAX_SUGGESTIONS = 5;

export function ContextMenuPlugin(): JSX.Element {
  const [editor] = useLexicalComposerContext();

  // Use refs to store spell data so it's available synchronously in $showOn
  const spellDataRef = useRef<{
    suggestions: string[];
    wordInfo: WordAtCursor | null;
  }>({ suggestions: [], wordInfo: null });

  // A right-click on an inline decorator (a chip or mention) leaves the
  // selection where it was, so remember which one the menu was opened on.
  const decoratorKeyRef = useRef<NodeKey | null>(null);

  // Initialize spell checker on mount
  useEffect(() => {
    initSpellCheck().catch(() => {
      // Spell check failed to load, continue without it
    });
  }, []);

  // Update spell data when context menu is about to show
  // This is called synchronously by NodeContextMenuPlugin's onContextMenu
  const updateSpellData = useCallback(() => {
    if (!isSpellCheckReady()) {
      spellDataRef.current = { suggestions: [], wordInfo: null };
      return;
    }

    const wordInfo = getWordAtCursor();
    if (wordInfo && !checkWord(wordInfo.word)) {
      const suggestions = getSuggestions(wordInfo.word, MAX_SUGGESTIONS);
      spellDataRef.current = { suggestions, wordInfo };
    } else {
      spellDataRef.current = { suggestions: [], wordInfo: null };
    }
  }, []);

  // Listen for context menu events to update spell data before menu renders
  useEffect(() => {
    const rootElement = editor.getRootElement();
    if (!rootElement) return;

    const handler = (event: MouseEvent) => {
      editor.read(() => {
        updateSpellData();
        const node = event.target instanceof Node ? $getNearestNodeFromDOMNode(event.target) : null;
        decoratorKeyRef.current = $isDecoratorNode(node) ? node.getKey() : null;
      });
    };

    // Use capture phase to run before NodeContextMenuPlugin's handler
    rootElement.addEventListener("contextmenu", handler, true);
    return () => {
      rootElement.removeEventListener("contextmenu", handler, true);
    };
  }, [editor, updateSpellData]);

  // Store spell option refs for title mutation
  const spellOptionsRef = useRef<NodeContextMenuOption[]>([]);

  // Create menu items - includes spell placeholders that show/hide via $showOn
  const items = useMemo(() => {
    // Create spell suggestion items for each slot
    const spellItems: (NodeContextMenuOption | NodeContextMenuSeparator)[] = [];
    spellOptionsRef.current = [];

    for (let i = 0; i < MAX_SUGGESTIONS; i++) {
      const option = new NodeContextMenuOption(`spell-suggestion-${i}`, {
        $onSelect: () => {
          const { suggestions, wordInfo } = spellDataRef.current;
          const suggestion = suggestions[i];
          if (!suggestion || !wordInfo) return;

          editor.update(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;

            const node = selection.anchor.getNode();
            if (!$isTextNode(node)) return;

            const textContent = node.getTextContent();
            const before = textContent.slice(0, wordInfo.startOffset);
            const after = textContent.slice(wordInfo.endOffset);
            const newText = before + suggestion + after;

            // Replace the text content
            const textNode = $createTextNode(newText);
            node.replace(textNode);

            // Position cursor after the replacement
            textNode.select(
              wordInfo.startOffset + suggestion.length,
              wordInfo.startOffset + suggestion.length
            );
          });
        },
        $showOn: () => {
          // Show this item only if we have a suggestion at this index
          const { suggestions } = spellDataRef.current;
          if (suggestions.length > i) {
            // Update the title dynamically when showing
            option.title = suggestions[i];
            return true;
          }
          return false;
        },
        disabled: false,
        icon: <SpellCheck className="h-4 w-4" />,
      });
      spellOptionsRef.current.push(option);
      spellItems.push(option);
    }

    // Add separator after spell suggestions (only shows if there are suggestions)
    spellItems.push(
      new NodeContextMenuSeparator({
        $showOn: () => spellDataRef.current.suggestions.length > 0,
      })
    );

    const baseItems = [
      new NodeContextMenuOption(`Remove Link`, {
        $onSelect: () => {
          editor.dispatchCommand(TOGGLE_LINK_COMMAND, null);
        },
        $showOn: (node: LexicalNode) => $isLinkNode(node.getParent()),
        disabled: false,
        icon: <Link2Off className="h-4 w-4" />,
      }),
      new NodeContextMenuSeparator({
        $showOn: (node: LexicalNode) => $isLinkNode(node.getParent()),
      }),
      new NodeContextMenuOption(`Cut`, {
        $onSelect: () => {
          editor.dispatchCommand(CUT_COMMAND, null);
        },
        disabled: false,
        icon: <Scissors className="h-4 w-4" />,
      }),
      new NodeContextMenuOption(`Copy`, {
        $onSelect: () => {
          editor.dispatchCommand(COPY_COMMAND, null);
        },
        disabled: false,
        icon: <Copy className="h-4 w-4" />,
      }),
      new NodeContextMenuOption(`Paste`, {
        $onSelect: () => {
          navigator.clipboard.read().then(async () => {
            const data = new DataTransfer();

            const readClipboardItems = await navigator.clipboard.read();
            const item = readClipboardItems[0];

            const permission = await navigator.permissions.query({
              // @ts-expect-error These types are incorrect.
              name: "clipboard-read",
            });
            if (permission.state === "denied") {
              alert("Not allowed to paste from clipboard.");
              return;
            }

            for (const type of item.types) {
              const dataString = await (await item.getType(type)).text();
              data.setData(type, dataString);
            }

            const event = new ClipboardEvent("paste", {
              clipboardData: data,
            });

            editor.dispatchCommand(PASTE_COMMAND, event);
          });
        },
        disabled: false,
        icon: <Clipboard className="h-4 w-4" />,
      }),
      new NodeContextMenuOption(`Paste as Plain Text`, {
        $onSelect: () => {
          navigator.clipboard.read().then(async () => {
            const permission = await navigator.permissions.query({
              // @ts-expect-error These types are incorrect.
              name: "clipboard-read",
            });

            if (permission.state === "denied") {
              alert("Not allowed to paste from clipboard.");
              return;
            }

            const data = new DataTransfer();
            const clipboardText = await navigator.clipboard.readText();
            data.setData("text/plain", clipboardText);

            const event = new ClipboardEvent("paste", {
              clipboardData: data,
            });
            editor.dispatchCommand(PASTE_COMMAND, event);
          });
        },
        disabled: false,
        icon: <ClipboardType className="h-4 w-4" />,
      }),
      new NodeContextMenuSeparator(),
      new NodeContextMenuOption(`Delete Node`, {
        $onSelect: () => {
          const decorator = decoratorKeyRef.current && $getNodeByKey(decoratorKeyRef.current);
          if (decorator) {
            decorator.remove();
            return;
          }
          const selection = $getSelection();
          if ($isRangeSelection(selection)) {
            const currentNode = selection.anchor.getNode();
            const ancestorNodeWithRootAsParent = currentNode.getParents().at(-2);

            ancestorNodeWithRootAsParent?.remove();
          } else if ($isNodeSelection(selection)) {
            const selectedNodes = selection.getNodes();
            selectedNodes.forEach((node) => {
              if ($isDecoratorNode(node)) {
                node.remove();
              }
            });
          }
        },
        disabled: false,
        icon: <Trash2 className="h-4 w-4" />,
      }),
    ];

    return [...spellItems, ...baseItems];
  }, [editor]);

  return (
    <NodeContextMenuPlugin
      className="EditorContextMenu overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md outline-none"
      itemClassName="relative w-full flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none select-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50"
      separatorClassName="bg-border -mx-1 h-px"
      items={items}
    />
  );
}
