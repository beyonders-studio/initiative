import { createContext, type ReactNode, useCallback, useContext, useRef } from "react";
import { useTranslation } from "react-i18next";

import { LazyImage } from "@/ui/lazy-image";
import { cn } from "@/ui/lib/utils";
import { useImageLightbox } from "@/ui/lightbox";

/** Set by a rendered link: a picture inside one is what the link opens, so
 *  the link keeps the click. */
const InLinkContext = createContext(false);

export const InLink = ({ children }: { children: ReactNode }) => (
  <InLinkContext value>{children}</InLinkContext>
);

interface ProseImageProps {
  src: string;
  alt?: string;
  title?: string;
  /** The picture itself — its size cap, border, corners. */
  className?: string;
  /** Fill the box it sits in, the picture fitted inside it — for a tile of a
   *  set size rather than a picture at its own. */
  fill?: boolean;
}

/**
 * A picture in rendered prose. It loads as it nears the screen and fades in,
 * as a collection's do, and inside an `ImageLightboxScope` it opens full size.
 * Outside a scope, or inside a link, it is just the picture.
 *
 * Its size is not known ahead, so no space is reserved: it keeps its own
 * width, capped at the column's, rather than being stretched to fill it.
 */
export const ProseImage = ({ src, alt = "", title, className, fill = false }: ProseImageProps) => {
  const { t } = useTranslation("common");
  const scope = useImageLightbox();
  const inLink = useContext(InLinkContext);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const register = scope?.register;

  const ref = useCallback(
    (button: HTMLButtonElement | null) => {
      buttonRef.current = button;
      return button && register ? register(button, { src, alt }) : undefined;
    },
    [register, src, alt]
  );

  const picture = (
    <LazyImage
      src={src}
      alt={alt}
      title={title}
      className={cn(
        "bg-transparent",
        fill ? "block h-full w-full" : "inline-block max-w-full align-bottom"
      )}
      imgClassName={cn(
        fill ? "h-full w-full object-contain" : "h-auto w-auto max-w-full object-contain",
        className
      )}
    />
  );

  if (!scope || inLink) return picture;

  return (
    <button
      ref={ref}
      type="button"
      aria-label={alt ? t("lightbox.openNamed", { name: alt }) : t("lightbox.open")}
      onClick={() => buttonRef.current && scope.open(buttonRef.current)}
      className={cn(
        "cursor-zoom-in rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        fill ? "block h-full w-full" : "inline-block max-w-full align-bottom"
      )}
    >
      {picture}
    </button>
  );
};
