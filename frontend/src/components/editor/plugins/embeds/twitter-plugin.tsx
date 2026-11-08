import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $insertNodeToNearestRoot } from "@lexical/utils";
import { COMMAND_PRIORITY_EDITOR, createCommand, type LexicalCommand } from "lexical";
import { type JSX, useEffect } from "react";

import { $createTweetNode, TweetNode } from "@/components/editor/nodes/embeds/tweet-node";

export const INSERT_TWEET_COMMAND: LexicalCommand<string> = createCommand("INSERT_TWEET_COMMAND");

export function TwitterPlugin(): JSX.Element | null {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    if (!editor.hasNodes([TweetNode])) {
      throw new Error("TwitterPlugin: TweetNode not registered on editor");
    }

    return editor.registerCommand<string>(
      INSERT_TWEET_COMMAND,
      (payload) => {
        const tweetNode = $createTweetNode(payload);
        $insertNodeToNearestRoot(tweetNode);

        return true;
      },
      COMMAND_PRIORITY_EDITOR
    );
  }, [editor]);

  return null;
}
