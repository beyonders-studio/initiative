import { MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

type RowActionsMenuProps = {
  /**
   * What the row is about — a handle, a name, a title. Read only by the
   * screen reader, so that a column of identical buttons still says which
   * row each one belongs to.
   */
  subject?: string;
  /** `DropdownMenuItem`s. Render nothing and the trigger doesn't draw. */
  children?: ReactNode;
  className?: string;
  /** Told when the menu opens or closes, for one that changes what it shows. */
  onOpenChange?: (open: boolean) => void;
};

/**
 * The one control at the end of a table row.
 *
 * A row's actions grow over time — a permission tier here, an account state
 * there — and laid out flat they wrap into a second and third line, push every
 * other column into a sliver, and put the destructive one under whichever
 * finger was reaching for the harmless one beside it. A menu holds any number
 * of them in fixed width, and puts them all a deliberate second click away.
 *
 * Callers pass only the items that apply, so this draws nothing at all for a
 * row with nothing to do — an empty trigger would promise otherwise.
 */
export const RowActionsMenu = ({
  subject,
  children,
  className,
  onOpenChange,
}: RowActionsMenuProps) => {
  const { t } = useTranslation("ui");

  // `Children.count` would count a `{false && …}` guard as an item; an array
  // of all-falsy children is the normal shape here, so test the rendered
  // result instead.
  const hasItems = Array.isArray(children) ? children.some(Boolean) : Boolean(children);
  if (!hasItems) return null;

  return (
    <div className={cn("flex justify-end", className)}>
      <DropdownMenu onOpenChange={onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={subject ? t("rowActions.labelFor", { subject }) : t("rowActions.label")}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {children}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};
