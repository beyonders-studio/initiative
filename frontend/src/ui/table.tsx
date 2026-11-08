import * as React from "react";

import { cn } from "@/ui/lib/utils";

interface TableProps extends React.HTMLAttributes<HTMLTableElement> {
  scrollContainerRef?: React.Ref<HTMLDivElement>;
  scrollContainerClassName?: string;
}

const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, scrollContainerRef, scrollContainerClassName, ...props }, ref) => (
    <div
      ref={scrollContainerRef}
      className={cn("relative w-full overflow-auto", scrollContainerClassName)}
    >
      <table ref={ref} className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  )
);
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

// A virtualized data table is drawn as two tables, its head kept at the top of
// the page apart from its body, under one element with the table role. The
// two tables are presentational, so the rows and cells in them name their own
// roles to stay one table's rows and cells.
const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      // biome-ignore lint/a11y/noRedundantRoles: a presentational table's rows need it, as above.
      role="row"
      className={cn(
        "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
        className
      )}
      {...props}
    />
  )
);
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    role="columnheader"
    className={cn(
      "h-10 px-2 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      className
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    // biome-ignore lint/a11y/noRedundantRoles: a presentational table's cells need it, as on the row.
    role="cell"
    className={cn(
      "p-2 align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      className
    )}
    {...props}
  />
));
TableCell.displayName = "TableCell";

export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow };
