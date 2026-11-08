import { HeadingNode } from "@lexical/rich-text";
import { mergeRegister } from "@lexical/utils";
import { defineExtension } from "lexical";

import { slugify } from "@/lib/slug";

export const HeadingAnchorExtension = defineExtension({
  name: "@initiative/heading-anchor",
  register: (editor) => {
    const handleClick = (event: Event) => {
      const mouseEvent = event as MouseEvent;
      const target = mouseEvent.target as HTMLElement;
      const anchor = target.closest("a");
      if (!anchor) return;

      const href = anchor.getAttribute("href");
      if (!href?.startsWith("#")) return;

      const rootElement = editor.getRootElement();
      if (!rootElement) return;

      const targetId = href.slice(1);
      const targetElement = rootElement.querySelector(`[id="${CSS.escape(targetId)}"]`);
      if (!targetElement) return;

      mouseEvent.preventDefault();
      mouseEvent.stopPropagation();
      targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    return mergeRegister(
      editor.registerMutationListener(
        HeadingNode,
        (mutations) => {
          editor.getEditorState().read(() => {
            for (const [nodeKey, type] of mutations) {
              if (type === "destroyed") continue;
              const dom = editor.getElementByKey(nodeKey);
              if (!dom) continue;
              const slug = slugify(dom.textContent || "");
              if (slug) {
                dom.id = slug;
              } else {
                dom.removeAttribute("id");
              }
            }
          });
        },
        { skipInitialization: false }
      ),
      editor.registerRootListener((rootElement, prevRootElement) => {
        if (prevRootElement) {
          prevRootElement.removeEventListener("click", handleClick, true);
        }
        if (rootElement) {
          rootElement.addEventListener("click", handleClick, true);
        }
      })
    );
  },
});
