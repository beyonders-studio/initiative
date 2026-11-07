import { Shield } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";

interface BulkAccessBarProps {
  count: number;
  /** Whether the current user can manage sharing on every selected item. */
  canManage: boolean;
  /** Why the action is unavailable, when the block isn't about permissions
   *  (e.g. an archived resource refuses sharing changes). */
  manageHint?: string;
  onEditAccess: () => void;
  onExit: () => void;
  /** Extra per-page actions rendered before "Edit access" (e.g. Export). */
  children?: ReactNode;
}

/**
 * The toolbar shown above a list while items are selected — a count, the
 * page's own actions, and an "Edit access" action.
 */
export function BulkAccessBar({
  count,
  canManage,
  manageHint,
  onEditAccess,
  onExit,
  children,
}: BulkAccessBarProps) {
  const { t } = useTranslation(["access", "common"]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary bg-primary/5 p-4">
      <div className="font-medium text-sm">{t("bulkBar.selected", { count })}</div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <Button
          variant="outline"
          size="sm"
          onClick={onEditAccess}
          disabled={count === 0 || !canManage}
          // Only explain the permission block when something is actually selected;
          // with nothing selected the button is simply inactive.
          title={count > 0 && !canManage ? (manageHint ?? t("bulkBar.needManage")) : undefined}
        >
          <Shield className="h-4 w-4" />
          {t("bulkBar.editAccess")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onExit}>
          {t("common:cancel")}
        </Button>
      </div>
    </div>
  );
}
