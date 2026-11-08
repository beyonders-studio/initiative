import type { ReactNode } from "react";

interface SelectionBarProps {
  /** How many are selected, in the caller's own words. */
  label: ReactNode;
  /** What can be done with the selection. */
  children: ReactNode;
}

/** The bar above a list while some of it is selected: how many, and what to do with them. */
export const SelectionBar = ({ label, children }: SelectionBarProps) => (
  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary bg-primary/5 p-4">
    <div className="font-medium text-sm">{label}</div>
    <div className="flex flex-wrap items-center gap-2">{children}</div>
  </div>
);
