/**
 * The shared furniture of an operator settings sheet: a labelled control with
 * its explanation, and the headed group such rows sit in.
 *
 * Both operator sheets — one for a community, one for an account — are the same
 * kind of surface: a list of unrelated controls, each saving on its own. They
 * read alike because they are built from these two pieces.
 */

import { Label } from "@/ui/label";
import { Separator } from "@/ui/separator";

/** One labelled control with its explanation, so every row reads the same. */
export const SettingRow = ({
  label,
  help,
  htmlFor,
  control,
}: {
  label: string;
  help: string;
  htmlFor?: string;
  control: React.ReactNode;
}) => (
  <div className="flex items-start justify-between gap-6 py-3">
    <div className="space-y-1">
      <Label htmlFor={htmlFor} className="font-medium">
        {label}
      </Label>
      <p className="text-muted-foreground text-sm">{help}</p>
    </div>
    <div className="shrink-0 pt-0.5">{control}</div>
  </div>
);

export const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="space-y-1">
    <h3 className="font-semibold text-sm">{title}</h3>
    <Separator />
    <div className="divide-y">{children}</div>
  </section>
);
