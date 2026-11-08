/**
 * Copying a tool, with everything inside it, into an initiative.
 *
 * One card for every tool that can be copied, because a copy is one route for
 * every kind (`POST /{tool}/{id}/duplicate`): the server takes the same steps
 * for all of them, and the only choices left are where the copy goes and what
 * it is called.
 */

import { useRouter } from "@tanstack/react-router";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolSettingsEntity,
  useToolSettings,
} from "@/components/tools/settings/ToolSettingsContext";
import { useDuplicateTool } from "@/hooks/toolHooks";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Whether this viewer may copy it: write on it, or read on a template, which
 *  is made to be copied. Where the copy may go is the dialog's question. A
 *  notice is published rather than reused, so posts offer no copy here. */
export const canUseDuplicateCard = (tool: Tool, entity: ToolSettingsEntity): boolean =>
  tool !== Tool.post && (entity.can.edit || Boolean(entity.is_template));

export const ToolDuplicateCard = () => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const gp = useCommunityPath();
  const { tool, entity } = useToolSettings();
  const { creatableInitiatives: creatable } = useToolCreateAccess(tool);
  // An initiative that keeps its content in is copied only beside itself, so
  // the card waits until it is known whether this one does.
  const source = useInitiative(entity.initiative_id ?? null);
  const keptIn = source.data?.keep_content_in;
  const creatableInitiatives = keptIn
    ? creatable.filter((i) => i.id === entity.initiative_id)
    : creatable;

  const [open, setOpen] = useState(false);
  const [initiativeId, setInitiativeId] = useState("");
  const [typedName, setTypedName] = useState<string | null>(null);

  const suggestedName = (id: string) =>
    id === String(entity.initiative_id)
      ? t("toolSettings.duplicate.defaultName", { name: entity.name })
      : entity.name;

  const duplicate = useDuplicateTool(tool, {
    onSuccess: (copy) => {
      const initiative = creatableInitiatives.find((i) => i.id === copy.initiative_id);
      toast.success(t("toolSettings.duplicate.duplicated", { initiative: initiative?.name }));
      setOpen(false);
      router.navigate({ to: gp(toolDetailRoute(tool, copy.initiative_id, copy.id)) });
    },
  });

  if (
    !canUseDuplicateCard(tool, entity) ||
    creatableInitiatives.length === 0 ||
    (entity.initiative_id != null && !source.isSuccess)
  ) {
    return null;
  }

  // The destination chosen, while it is still offered: an initiative that
  // starts keeping its content in with the dialog open takes the choice back
  // to itself.
  const destination = creatableInitiatives.some((i) => String(i.id) === initiativeId)
    ? initiativeId
    : String(creatableInitiatives[0].id);
  // A name typed stays; until then it is the suggestion for the destination.
  const name = typedName ?? suggestedName(destination);

  const openDialog = () => {
    const here = creatableInitiatives.some((i) => i.id === entity.initiative_id);
    const id = String(here ? entity.initiative_id : creatableInitiatives[0].id);
    setInitiativeId(id);
    setTypedName(null);
    setOpen(true);
  };

  const submit = () => {
    if (!name.trim()) return;
    duplicate.mutate({
      id: entity.id,
      data: { name: name.trim(), target_initiative_id: Number(destination) },
    });
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("toolSettings.duplicate.title")}</CardTitle>
          <CardDescription>{t("toolSettings.duplicate.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" variant="outline" onClick={openDialog}>
            <Copy className="h-4 w-4" />
            {t("toolSettings.duplicate.action")}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("toolSettings.duplicate.dialogTitle", { name: entity.name })}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t("toolSettings.duplicate.description")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field label={t("toolSettings.duplicate.initiative")}>
              <Select value={destination} onValueChange={setInitiativeId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("name")}>
              <Input
                value={name}
                onChange={(event) => setTypedName(event.target.value)}
                placeholder={t("toolSettings.namePlaceholder")}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submit();
                }}
              />
            </Field>
          </div>
          <DialogFooter
            submitLabel={t("toolSettings.duplicate.action")}
            onSubmit={submit}
            pending={duplicate.isPending}
            pendingLabel={t("toolSettings.duplicate.duplicating")}
            disabled={!name.trim()}
          />
        </DialogContent>
      </Dialog>
    </>
  );
};
