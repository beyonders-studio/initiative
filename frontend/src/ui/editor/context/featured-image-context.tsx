import { createContext, useContext } from "react";

/** The featured image of the document an editor is writing, for the editor's
 *  pictures to be made it. Where nothing provides it, no picture offers to be. */
export interface FeaturedImage {
  url: string | null;
  set: (url: string) => void;
}

const FeaturedImageContext = createContext<FeaturedImage | null>(null);

export const FeaturedImageProvider = FeaturedImageContext.Provider;

export const useFeaturedImage = (): FeaturedImage | null => useContext(FeaturedImageContext);
