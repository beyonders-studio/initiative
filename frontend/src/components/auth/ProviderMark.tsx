/**
 * One provider's mark, at whatever size the place it sits in wants.
 *
 * Decorative: every place this appears names the provider beside it, so the
 * mark repeats what the label already says and is hidden from anything
 * reading the page aloud.
 */

import { providerIcon } from "@/lib/authProviderIcons";
import { cn } from "@/ui/lib/utils";

export interface ProviderMarkProps {
  icon: string | null | undefined;
  className?: string;
}

export const ProviderMark = ({ icon, className }: ProviderMarkProps) => {
  const Mark = providerIcon(icon);
  return (
    <Mark
      aria-hidden="true"
      // The brand marks name themselves in a <title> by default, which would
      // put the provider's name in the page twice over.
      title=""
      // `currentColor` either way, so the mark takes the weight of the text
      // beside it rather than sitting at full brand contrast in a list.
      className={cn("h-5 w-5 shrink-0 text-muted-foreground", className)}
    />
  );
};
