import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { WhenYouSave } from "@/components/settings/SettingsSection";
import { useServerForm } from "@/hooks/useServerForm";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

export interface OnOffRuleDialogProps {
  /** Names the radio buttons, so two of these on one page stay apart. */
  id: string;
  title: string;
  description: string;
  onLabel: string;
  offLabel: string;
  saved: boolean;
  /** What turning it on reaches, a line each. Shown only while the choice
   *  turns on a rule that is off. */
  impact?: (string | false)[];
  pending: boolean;
  onSave: (on: boolean) => void;
  /** Told when the choice changes, for a caller showing a refusal of the last
   *  choice. */
  onChoose?: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Shown under the choice: a refusal and the way to answer it. */
  children?: ReactNode;
}

/**
 * A rule that is on or off, changed in a dialog. Turning one on says who it
 * reaches before it saves. Each opening starts from what is saved.
 */
export const OnOffRuleDialog = ({
  id,
  title,
  description,
  onLabel,
  offLabel,
  saved,
  impact = [],
  pending,
  onSave,
  onChoose,
  open,
  onOpenChange,
  children,
}: OnOffRuleDialogProps) => {
  const { t } = useTranslation("common");
  const form = useServerForm(saved, (loaded) => ({ on: loaded ?? false }), open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RadioGroup
            value={form.values.on ? "on" : "off"}
            onValueChange={(value) => {
              form.set({ on: value === "on" });
              onChoose?.();
            }}
            className="gap-3"
          >
            {(["off", "on"] as const).map((value) => (
              <div key={value} className="flex items-center gap-3 rounded-md border px-4 py-3">
                <RadioGroupItem id={`${id}-${value}`} value={value} />
                <Label htmlFor={`${id}-${value}`} className="font-medium text-base">
                  {value === "on" ? onLabel : offLabel}
                </Label>
              </div>
            ))}
          </RadioGroup>
          {/* Only turning a rule on reaches anybody; turning it off just saves. */}
          <WhenYouSave lines={form.values.on && !saved ? impact : []} />
          {children}
        </div>
        <DialogFooter
          submitLabel={t("save")}
          pending={pending}
          disabled={form.values.on === saved}
          onSubmit={() => onSave(form.values.on)}
        />
      </DialogContent>
    </Dialog>
  );
};
