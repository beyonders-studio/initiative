import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { useCommunityPath } from "@/lib/communityUrl";
import { cardVariants } from "@/ui/card";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

interface ToolCardProps {
  /** Its page, inside the community. */
  to: string;
  name: string;
  description?: string | null;
  tags: TagSummary[];
  /** What it is, beside its name: an icon or a face. */
  mark?: ReactNode;
  /** A picture of what is in it, across the top. */
  preview?: ReactNode;
  /** Lines of its own, under the name and before the tags. */
  children?: ReactNode;
}

/**
 * One thing on a tool's list, the whole card a link to its page. The name is
 * cut at one line, with all of it on hover, and the description at two; each
 * tag opens its own page from inside the card's link.
 */
export const ToolCard = ({
  to,
  name,
  description,
  tags,
  mark,
  preview,
  children,
}: ToolCardProps) => {
  const gp = useCommunityPath();

  return (
    <Link to={gp(to)} className={cardVariants({ variant: "tile" })}>
      {preview}
      {/* With nothing above it, the body stops short of the bookmark the list
          puts on the card's corner. */}
      <div className={cn("flex items-start gap-3 p-4", !preview && "pr-14")}>
        {mark}
        <div className="min-w-0 flex-1 space-y-1">
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <h3 className="line-clamp-1 font-semibold text-lg leading-tight">{name}</h3>
              </TooltipTrigger>
              <TooltipContent side="top" align="start">
                <p>{name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {description ? (
            <p className="line-clamp-2 text-muted-foreground text-sm">{description}</p>
          ) : null}
          {children}
          <TagBadgeList
            tags={tags}
            tagHref={(tag) => gp(`/tags/${tag.id}`)}
            nested
            className="pt-1"
          />
        </div>
      </div>
    </Link>
  );
};
