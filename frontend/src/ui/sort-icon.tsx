import type { RowData } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Button } from "@/ui/button";
import type { AppColumn } from "@/ui/lib/table";

export const SortIcon = ({ isSorted }: { isSorted: boolean | "asc" | "desc" }) => {
  if (!isSorted) return <ArrowUpDown className="h-4 w-4" aria-hidden="true" />;
  if (isSorted === "asc") return <ArrowUp className="h-4 w-4" aria-hidden="true" />;
  if (isSorted === "desc") return <ArrowDown className="h-4 w-4" aria-hidden="true" />;
};

/** A column header that toggles that column's sort. */
export const SortHeader = <TData extends RowData>({
  column,
  label,
  className,
}: {
  column: AppColumn<TData>;
  label: string;
  className?: string;
}) => {
  const isSorted = column.getIsSorted();
  return (
    <Button
      variant="ghost"
      className={className}
      onClick={() => column.toggleSorting(isSorted === "asc")}
    >
      {label}
      <SortIcon isSorted={isSorted} />
    </Button>
  );
};
