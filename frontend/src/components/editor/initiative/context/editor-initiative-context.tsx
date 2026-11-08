import { createContext, useContext } from "react";

/**
 * The initiative the page being edited belongs to — what a reference made from
 * inside it may point at. Provided above the composer, so a decorator (which
 * the composer portals in itself) reads it too.
 */
export const EditorInitiativeContext = createContext<number | null>(null);

export const useEditorInitiative = () => useContext(EditorInitiativeContext);
