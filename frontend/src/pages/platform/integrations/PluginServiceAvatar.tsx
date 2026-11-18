import { Blocks } from "lucide-react";

import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { cn } from "@/ui/lib/utils";

/**
 * A plug-in service's art, from its listing, as the marketplace draws it. One
 * whose listing has not arrived yet shows the plug-ins icon in its place.
 */
export const PluginServiceAvatar = ({
  registration,
  className,
}: {
  registration: PluginServiceRegistrationRead;
  className?: string;
}) => {
  const src = resolveArtworkUrl(registration.avatar_url);
  return src ? (
    <img
      src={src}
      alt=""
      aria-hidden
      className={cn("shrink-0 rounded-lg object-cover", className)}
      loading="lazy"
    />
  ) : (
    <div
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground",
        className
      )}
    >
      <Blocks className="size-1/2" />
    </div>
  );
};
