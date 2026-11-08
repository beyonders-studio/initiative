import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCreateTool } from "@/hooks/useCreateTool";
import { useInitiative } from "@/hooks/useInitiatives";
import { TOOL_ICONS, TOOLS, toolNavLabelKey } from "@/lib/tools";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { cn } from "@/ui/lib/utils";

/** What a made thing answers with, so the caller can link it. */
export interface CreatedThing {
  entityType: SearchEntityType;
  entityId: number;
  name: string;
}

interface CreateReferencedThingDialogProps {
  /** The name that was typed and found nothing. */
  name: string;
  initiativeId: number;
  /** Made, and ready to be referred to. */
  onCreated: (created: CreatedThing) => void;
  onClose: () => void;
}

/**
 * Making the thing `[[ ]]` could not find.
 *
 * Every tool is made the same way — a name and the initiative the writer is
 * already in — which is exactly why `[[ ]]` reaches tools and `#` does not
 * reach further. It creates in place and hands the reference back, so the
 * sentence being written is never abandoned to go and make something.
 *
 * Only tools this initiative has and this writer may add are offered: creating
 * one that is switched off would be a way around the switch.
 */
export function CreateReferencedThingDialog({
  name,
  initiativeId,
  onCreated,
  onClose,
}: CreateReferencedThingDialogProps) {
  const { t } = useTranslation(["comments", "common", "nav"]);
  const { data: initiative } = useInitiative(initiativeId);
  const [chosen, setChosen] = useState<Tool | null>(null);

  const createTool = useCreateTool();

  const offered = TOOLS.filter((tool) => initiative?.can.create.includes(tool));

  const create = async () => {
    if (chosen === null) return;
    const made = await createTool.mutateAsync({
      tool: chosen,
      name,
      initiativeId,
    });
    onCreated({
      entityType: chosen as unknown as SearchEntityType,
      entityId: made.id,
      name,
    });
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("createNamed", { name })}</DialogTitle>
          <DialogDescription>{t("createKindPrompt")}</DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2">
          {offered.map((tool) => {
            const Icon = TOOL_ICONS[tool];
            return (
              <button
                key={tool}
                type="button"
                onClick={() => setChosen(tool)}
                className={cn(
                  "flex items-center gap-2 rounded-md border-2 px-3 py-2 text-left text-sm",
                  chosen === tool
                    ? "border-primary bg-primary/5"
                    : "border-transparent bg-muted hover:border-muted-foreground/30"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {t(`nav:${toolNavLabelKey(tool)}` as never)}
              </button>
            );
          })}
        </div>
        {offered.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("createNothingAllowed")}</p>
        )}

        <DialogFooter
          submitLabel={t("common:create")}
          onSubmit={() => void create()}
          pending={createTool.isPending}
          disabled={chosen === null}
        />
      </DialogContent>
    </Dialog>
  );
}
