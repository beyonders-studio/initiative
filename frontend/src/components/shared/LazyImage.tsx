import { type ImgHTMLAttributes, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface LazyImageProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> {
  src: string | null | undefined;
  /** Width over height. Reserves the picture's space before its bytes arrive,
   *  so a wall of them does not reflow as each one lands. */
  aspectRatio?: number | null;
  /** The box around the picture — what carries the placeholder colour and
   *  the reserved shape. */
  className?: string;
  /** The picture itself, once it is there. */
  imgClassName?: string;
  /** How far ahead of the viewport the bytes are asked for. */
  rootMargin?: string;
}

/**
 * A picture that arrives rather than pops.
 *
 * Two things a plain `<img>` does not do on a wall of forty. It waits: the
 * bytes are not requested until the box is near the viewport, so opening a
 * collection costs a screen of pictures, not the whole collection. And it fades:
 * the box is drawn at the picture's shape from the start, in the placeholder
 * colour, and the picture fades in over it once decoded — so the wall keeps
 * its layout while it fills and nothing flashes from blank to loaded.
 *
 * A picture already in the browser's cache fires `onLoad` before the effect
 * that watches for it, so `complete` is checked on mount as well; without
 * that a cached picture would sit at opacity zero forever.
 */
export const LazyImage = ({
  src,
  alt = "",
  aspectRatio,
  className,
  imgClassName,
  rootMargin = "400px",
  style,
  ...imgProps
}: LazyImageProps) => {
  const boxRef = useRef<HTMLSpanElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [near, setNear] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    // No observer (an old WebView, jsdom): load straight away rather than
    // never.
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin }
    );
    observer.observe(box);
    return () => observer.disconnect();
  }, [rootMargin]);

  useEffect(() => {
    if (near && imgRef.current?.complete && imgRef.current.naturalWidth > 0) {
      setLoaded(true);
    }
  }, [near]);

  // A new picture in the same box starts over.
  useEffect(() => {
    setLoaded(false);
  }, [src]);

  // A span, so the picture can sit in a paragraph of rendered prose.
  return (
    <span
      ref={boxRef}
      className={cn("relative block overflow-hidden bg-muted", className)}
      style={{
        ...(aspectRatio ? { aspectRatio: String(aspectRatio) } : {}),
        ...style,
      }}
    >
      {near && src ? (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          // A picture already on the page is not a file to drop somewhere
          // else on it. Without this the browser offers the image as a
          // drag, and a wall that takes drops takes its own pictures back.
          draggable={false}
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          className={cn(
            "h-full w-full object-cover transition-opacity duration-300 ease-out",
            loaded ? "opacity-100" : "opacity-0",
            imgClassName
          )}
          {...imgProps}
        />
      ) : null}
    </span>
  );
};
