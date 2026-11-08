import { createContext, useContext } from "react";

/** The featured image of the file an editor is writing, for the editor's
 *  pictures to be made it. Nothing provides it outside a file page, so a
 *  comment or a post offers no such thing. */
export interface FeaturedImage {
  url: string | null;
  set: (url: string) => void;
}

const FeaturedImageContext = createContext<FeaturedImage | null>(null);

export const FeaturedImageProvider = FeaturedImageContext.Provider;

export const useFeaturedImage = (): FeaturedImage | null => useContext(FeaturedImageContext);

/** Only a file stored in the community can be featured — the shape the server
 *  holds `featured_image_url` to (`UPLOAD_PATH_SHAPE`). */
export const canBeFeatured = (src: string): boolean => /^\/uploads\/\d+\/[\w.-]+$/.test(src);
