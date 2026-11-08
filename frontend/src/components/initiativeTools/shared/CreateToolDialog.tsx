import type { FlatNamespace } from "i18next";
import { Loader2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toolKebabSingular } from "@/lib/tools";
import type { DialogProps } from "@/types/dialog";
import type { TranslateFn } from "@/types/i18n";
import type { MutationOpts } from "@/types/mutation";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

/** The keys a tool spells its create dialog with, in its own namespace. */
export type CreateToolText = {
  ns: FlatNamespace;
  /** Title of the dialog and its submit button. */
  create: string;
  /** The line under the title. */
  createDescription?: string;
  /** For a namespace whose `descriptionPlaceholder` already says something else. */
  descriptionPlaceholder?: string;
};

/** What this dialog sends, whichever tool it makes. */
type ToolCreatePayload = {
  name: string;
  description?: string;
  initiative_id?: number;
  grants: ResourceGrantSchema[];
};

/**
 * The slice of a tool's `TOOL_HOOKS` create hook this dialog drives. Each is
 * typed with its own tool's schemas, and every one of them takes this payload.
 */
type ToolCreateHook = (options: MutationOpts<{ id: number }, ToolCreatePayload>) => {
  mutate: (payload: ToolCreatePayload) => void;
  isPending: boolean;
};

export type CreateToolDialogProps = DialogProps & {
  tool: Tool;
  text: CreateToolText;
  /** If provided, the initiative is locked and cannot be changed. */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but the user can change it). */
  defaultInitiativeId?: number;
  /** Create one belonging to the community rather than to any initiative, the way
   * the calendar plug-in's own calendars do. There is no initiative to pick. */
  communityScope?: boolean;
  /** Fields only this tool asks for, shown under the description, and what
   * they add to what is sent. */
  extra?: { field: ReactNode; payload: Record<string, unknown> };
  /** Called after successful creation. */
  onSuccess?: (created: { id: number }) => void;
};

/**
 * Naming a new, empty tool: its name, a description, the initiative it goes
 * in, and who else may reach it. Every tool made by naming an empty container
 * is made here, and what differs between them is their strings and the odd
 * field of their own. Files, posts and projects start from content or a
 * template, and keep dialogs of their own.
 */
export const CreateToolDialog = ({
  open,
  onOpenChange,
  tool,
  text,
  initiativeId,
  defaultInitiativeId,
  communityScope = false,
  extra,
  onSuccess,
}: CreateToolDialogProps) => {
  // The namespace and several keys come from the tool, so use the loose
  // translation signature rather than the statically-typed keys.
  const { t: translate } = useTranslation(text.ns);
  const t = translate as TranslateFn;
  const idPrefix = `create-${toolKebabSingular(tool)}`;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);

  const initiativesQuery = useInitiatives();
  const initiatives = initiativesQuery.data ?? [];

  // The picker only offers initiatives the user may actually create this tool
  // in (server-computed create flags; folds in the tool's master switch). A
  // community-level one goes into none of them, so the question is not asked.
  const { creatableInitiatives } = useToolCreateAccess(tool, { enabled: open && !communityScope });

  const effectiveInitiativeId = communityScope
    ? null
    : (initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null));

  const lockedInitiative = initiativeId
    ? (initiatives.find((i) => i.id === initiativeId) ?? null)
    : null;

  // Reset form when dialog closes, set default initiative when dialog opens
  useEffect(() => {
    if (open) {
      if (communityScope) return;
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      } else if (creatableInitiatives.length === 1) {
        setSelectedInitiativeId(String(creatableInitiatives[0].id));
      }
    } else {
      setName("");
      setDescription("");
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
      setGrants([...DEFAULT_GRANTS]);
    }
  }, [open, communityScope, defaultInitiativeId, creatableInitiatives]);

  // Every tool but a file has a create hook in the table; each is typed
  // with its own schemas, which this payload satisfies.
  const { useCreate } = TOOL_HOOKS[tool] as unknown as { useCreate: ToolCreateHook };
  const createTool = useCreate({
    onSuccess: (result) => {
      onOpenChange(false);
      onSuccess?.(result);
    },
  });

  const isCreating = createTool.isPending;
  const hasTarget = communityScope || !!effectiveInitiativeId;
  const canSubmit = !!name.trim() && hasTarget && !isCreating;

  const handleSubmit = () => {
    const trimmedName = name.trim();
    if (!trimmedName || !hasTarget) return;
    createTool.mutate({
      ...extra?.payload,
      name: trimmedName,
      description: description.trim() || undefined,
      // Omitted for a community-level one: no initiative is what makes it one.
      ...(effectiveInitiativeId ? { initiative_id: effectiveInitiativeId } : {}),
      grants,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(text.create)}</DialogTitle>
          {text.createDescription ? (
            <DialogDescription>{t(text.createDescription)}</DialogDescription>
          ) : null}
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-name`}>{t("name")}</Label>
            <Input
              id={`${idPrefix}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-description`}>{t("description")}</Label>
            <Textarea
              id={`${idPrefix}-description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t(text.descriptionPlaceholder ?? "descriptionPlaceholder")}
              rows={3}
            />
          </div>

          {extra?.field}

          {communityScope ? null : (
            <div className="space-y-2">
              <Label htmlFor={`${idPrefix}-initiative`}>{t("initiative")}</Label>
              {initiativeId ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {lockedInitiative?.name ?? t("selectInitiative")}
                </div>
              ) : (
                <Select
                  value={selectedInitiativeId}
                  onValueChange={(value) => {
                    setSelectedInitiativeId(value);
                    // Access grants are initiative-scoped; a new target starts
                    // over with default access.
                    setGrants([...DEFAULT_GRANTS]);
                  }}
                >
                  <SelectTrigger id={`${idPrefix}-initiative`}>
                    <SelectValue placeholder={t("selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {creatableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          <CreateAccessSection
            initiativeId={effectiveInitiativeId}
            grants={grants}
            onChange={setGrants}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isCreating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("creating")}
              </>
            ) : (
              t(text.create)
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
