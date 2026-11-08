import { AutoLinkNode, LinkNode } from "@lexical/link";
import { mergeRegister } from "@lexical/utils";
import { defineExtension } from "lexical";

import { sanitizeUrl } from "@/ui/lib/safeUrl";

/** A link's stored address is the one `sanitizeUrl` gives it, however the link arrived. */
export const LinkSanitizeExtension = defineExtension({
  name: "@initiative/link-sanitize",
  register: (editor) => {
    const $sanitize = (node: LinkNode) => {
      const url = node.getURL();
      const safe = sanitizeUrl(url);
      if (safe !== url) node.setURL(safe);
    };
    return mergeRegister(
      editor.registerNodeTransform(LinkNode, $sanitize),
      editor.registerNodeTransform(AutoLinkNode, $sanitize)
    );
  },
});
