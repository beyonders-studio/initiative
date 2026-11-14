/**
 * The title and description a front-door page gives the browser tab and
 * search engines. The static `index.html` names every page "Initiative";
 * each front-door page says what it is instead, and puts the old values
 * back when it leaves so the app's own screens are unaffected.
 */

import { useEffect } from "react";

const describe = (content: string) => {
  let tag = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (!tag) {
    tag = document.createElement("meta");
    tag.name = "description";
    document.head.appendChild(tag);
  }
  const previous = tag.content;
  tag.content = content;
  return () => {
    tag.content = previous;
  };
};

export const usePageMeta = (title: string, description: string) => {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;
    const restoreDescription = describe(description);
    return () => {
      document.title = previousTitle;
      restoreDescription();
    };
  }, [title, description]);
};
