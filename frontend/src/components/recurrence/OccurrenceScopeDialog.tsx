import { type ReactNode, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarEventUpdateScope } from "@/api/generated/initiativeAPI.schemas";
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

export type OccurrenceScope = NonNullable<CalendarEventUpdateScope>;

/** What the change is: it names the dialog and its button. */
export type ScopeAction = "edit" | "delete" | "duplicate";

const SCOPES: OccurrenceScope[] = ["this", "following", "all"];

/** Whose series it is: the namespace holding its `scope.*` wording. */
export type ScopeTool = "calendars" | "tasks";

export type ScopeQuestion = {
  tool?: ScopeTool;
  /** How many the whole series holds, shown beside "all". */
  count?: number;
  /** The choices that differ for this change; all three by default. */
  scopes?: OccurrenceScope[];
};

type OccurrenceScopeDialogProps = ScopeQuestion & {
  action: ScopeAction;
  onChoose: (scope: OccurrenceScope | null) => void;
};

/**
 * Which occurrences of a repeating event or task an edit or a delete is for.
 * An answer is always for one event, so it is never asked.
 */
export const OccurrenceScopeDialog = ({
  action,
  onChoose,
  tool = "calendars",
  count,
  scopes = SCOPES,
}: OccurrenceScopeDialogProps) => {
  const { t } = useTranslation([tool, "common"]);
  const [scope, setScope] = useState<OccurrenceScope>("this");
  return (
    <Dialog open onOpenChange={(open) => !open && onChoose(null)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t(`scope.title.${action}`)}</DialogTitle>
          <DialogDescription>{t("scope.description")}</DialogDescription>
        </DialogHeader>
        <RadioGroup value={scope} onValueChange={(value) => setScope(value as OccurrenceScope)}>
          {scopes.map((option) => (
            <div key={option} className="flex items-center gap-3">
              <RadioGroupItem value={option} id={`occurrence-scope-${option}`} />
              <Label htmlFor={`occurrence-scope-${option}`} className="cursor-pointer">
                {option === "all" && count !== undefined
                  ? t("scope.allCount", { count })
                  : t(`scope.${option}`)}
              </Label>
            </div>
          ))}
        </RadioGroup>
        <DialogFooter
          submitLabel={t(`scope.confirm.${action}`)}
          onSubmit={() => onChoose(scope)}
          destructive={action === "delete"}
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * Ask which occurrences a change is for, as a promise: the scope picked, or
 * `null` when the dialog was closed. Render `dialog` once in the page.
 */
export const useScopePrompt = (): {
  ask: (action: ScopeAction, question?: ScopeQuestion) => Promise<OccurrenceScope | null>;
  dialog: ReactNode;
} => {
  const [asking, setAsking] = useState<
    | (ScopeQuestion & {
        action: ScopeAction;
        resolve: (scope: OccurrenceScope | null) => void;
      })
    | null
  >(null);
  const ask = useCallback(
    (action: ScopeAction, question?: ScopeQuestion) =>
      new Promise<OccurrenceScope | null>((resolve) => setAsking({ ...question, action, resolve })),
    []
  );
  const dialog = asking ? (
    <OccurrenceScopeDialog
      {...asking}
      onChoose={(scope) => {
        asking.resolve(scope);
        setAsking(null);
      }}
    />
  ) : null;
  return { ask, dialog };
};
