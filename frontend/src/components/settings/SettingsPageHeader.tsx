import type { ReactNode } from "react";

export interface SettingsPageHeaderProps {
  title: string;
  /** The muted line under the title. */
  description?: ReactNode;
  /** Notices under the title, above the description. */
  children?: ReactNode;
}

/** The title of a settings area, above its tab bar. */
export const SettingsPageHeader = ({ title, description, children }: SettingsPageHeaderProps) => (
  <header className="space-y-2">
    <h1 className="font-semibold text-3xl tracking-tight">{title}</h1>
    {children}
    {description ? <p className="text-muted-foreground text-sm">{description}</p> : null}
  </header>
);
