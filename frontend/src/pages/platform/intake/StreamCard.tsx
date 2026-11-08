import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Conversation,
  type IntakeBindingRead,
  type IntakeBindingUpsert,
  type IntakeInitiativeOption,
  type IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useDeleteIntakeBinding,
  useImportIntakeBlueprint,
  useUpsertIntakeBinding,
} from "@/hooks/useIntakeSettings";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { formatDateTime } from "@/ui/lib/formatDate";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

/** Sentinel for "no community", which a Select cannot express with "". */
export const NONE = "none";

interface StreamCardProps {
  binding: IntakeBindingRead;
  initiatives: IntakeInitiativeOption[];
  /** Both reads have settled, so bindings and options describe one community. */
  settled: boolean;
}

export const StreamCard = ({ binding, initiatives, settled }: StreamCardProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;

  const [initiativeId, setInitiativeId] = useState<string>("");
  const [unbinding, setUnbinding] = useState(false);

  const importBlueprint = useImportIntakeBlueprint({
    onSuccess: (result) => toast.success(t("stream.createdToast", { name: result.project_name })),
  });
  const upsert = useUpsertIntakeBinding();
  const remove = useDeleteIntakeBinding({
    onSuccess: () => toast.success(t("stream.unboundToast")),
  });

  // Every project in the community, flattened, labelled by its initiative —
  // the picker is a list of destinations, and the initiative is context on
  // each rather than a second choice to make first.
  const projects = useMemo(
    () =>
      initiatives.flatMap((initiative) =>
        initiative.projects.map((project) => ({
          ...project,
          initiativeName: initiative.name,
        }))
      ),
    [initiatives]
  );
  const bound = useMemo(
    () => projects.find((project) => project.id === binding.project_id),
    [projects, binding.project_id]
  );
  const statuses = bound?.statuses ?? [];
  const types = bound?.task_types ?? [];
  const ideas = stream === "ideas";

  const busy = !settled || importBlueprint.isPending || upsert.isPending || remove.isPending;

  // A PUT replaces the whole binding, so each change carries the rest of it.
  const save = (changes: Partial<IntakeBindingUpsert>) =>
    upsert.mutate({
      stream,
      body: {
        project_id: binding.project_id as number,
        default_status_id: binding.default_status_id ?? null,
        task_type_id: binding.task_type_id ?? null,
        awaiting_filer_status_id: binding.awaiting_filer_status_id ?? null,
        active_status_id: binding.active_status_id ?? null,
        enabled: binding.enabled,
        ...changes,
      },
    });
  const statusOption = (id: number | null | undefined) => (id ? String(id) : NONE);
  const statusValue = (value: string) => (value === NONE ? null : Number(value));

  // Each stream's card is a landmark named by its own title, so a screen
  // reader announces which stream a control belongs to rather than reading
  // four identical sets of pickers.
  const titleId = `intake-stream-${stream}`;

  return (
    <Card role="region" aria-labelledby={titleId}>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle id={titleId}>{t(`streams.${stream}.title`)}</CardTitle>
            <CardDescription>{t(`streams.${stream}.description`)}</CardDescription>
          </div>
          {binding.project_id === null ? (
            <Badge variant="outline">{t("stream.notSetUp")}</Badge>
          ) : binding.project_archived ? (
            // Archived content takes no writes, so this stream receives
            // nothing however its own switch is set. Say that, rather than
            // "Receiving".
            <Badge variant="destructive">{t("stream.destinationArchived")}</Badge>
          ) : (
            <Badge variant={binding.enabled ? "default" : "secondary"}>
              {binding.enabled ? t("stream.receiving") : t("stream.paused")}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {binding.project_id === null ? (
          <div className="space-y-3">
            <p className="text-muted-foreground text-sm">{t("stream.setUpHelp")}</p>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("stream.initiativeLabel")}>
                <Select value={initiativeId} onValueChange={setInitiativeId} disabled={busy}>
                  <SelectTrigger className="w-64">
                    <SelectValue placeholder={t("stream.initiativePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {initiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Button
                disabled={busy || !initiativeId}
                onClick={() =>
                  importBlueprint.mutate({ stream, initiativeId: Number(initiativeId) })
                }
              >
                {t("stream.setUpForMe")}
              </Button>
            </div>
            <Field label={t("stream.existingProjectLabel")} className="border-t pt-4">
              <Select
                value=""
                disabled={busy || projects.length === 0}
                onValueChange={(value) =>
                  upsert.mutate({ stream, body: { project_id: Number(value), enabled: true } })
                }
              >
                <SelectTrigger className="max-w-md">
                  <SelectValue placeholder={t("stream.existingProjectPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      {project.initiativeName} › {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Repointing starts fresh in the new project: an incident still
                open in the old one stays where the work on it is. */}
            <Field
              label={t("stream.landsInLabel")}
              hint={!binding.project_archived && t("stream.repointNote")}
              error={binding.project_archived && t("stream.archivedNote")}
            >
              <Select
                value={String(binding.project_id)}
                disabled={busy}
                onValueChange={(value) =>
                  upsert.mutate({
                    stream,
                    body: { project_id: Number(value), enabled: binding.enabled },
                  })
                }
              >
                <SelectTrigger className="max-w-md">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* An archived project is not offered as a destination, so
                      the one already bound has to name itself or the control
                      would render blank. */}
                  {binding.project_archived && (
                    <SelectItem value={String(binding.project_id)} disabled>
                      {t("stream.archivedOption", { name: binding.project_name ?? "" })}
                    </SelectItem>
                  )}
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      {project.initiativeName} › {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label={t("stream.landingStatusLabel")}>
              <Select
                value={binding.default_status_id ? String(binding.default_status_id) : NONE}
                disabled={busy || statuses.length === 0}
                onValueChange={(value) => save({ default_status_id: statusValue(value) })}
              >
                <SelectTrigger className="max-w-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t("stream.landingStatusDefault")}</SelectItem>
                  {statuses.map((status) => (
                    <SelectItem key={status.id} value={String(status.id)}>
                      {status.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            {/* A project with one type has nothing to choose, except on the
                Ideas board, where the type is what publishes an idea. */}
            {types.length > 1 || binding.task_type_id || ideas ? (
              <Field label={t(ideas ? "stream.ideaTypeLabel" : "stream.caseTypeLabel")}>
                <Select
                  value={statusOption(binding.task_type_id)}
                  disabled={busy}
                  onValueChange={(value) => save({ task_type_id: statusValue(value) })}
                >
                  <SelectTrigger className="max-w-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>
                      {t(ideas ? "stream.ideaTypeNone" : "stream.caseTypeDefault")}
                    </SelectItem>
                    {/* One the project no longer offers names itself, or the
                        control would render blank. */}
                    {binding.task_type_id &&
                    !types.some((type) => type.id === binding.task_type_id) ? (
                      <SelectItem value={String(binding.task_type_id)} disabled>
                        {binding.task_type_name ?? ""}
                      </SelectItem>
                    ) : null}
                    {types.map((type) => (
                      <SelectItem key={type.id} value={String(type.id)}>
                        {type.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            ) : null}

            {binding.conversation && binding.conversation !== Conversation.none ? (
              <div className="space-y-3">
                <div className="grid grid-cols-pair gap-3">
                  <Field label={t("stream.awaitingLabel")}>
                    <Select
                      value={statusOption(binding.awaiting_filer_status_id)}
                      disabled={busy || statuses.length === 0}
                      onValueChange={(value) =>
                        save({ awaiting_filer_status_id: statusValue(value) })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE}>{t("stream.noStatusRole")}</SelectItem>
                        {statuses.map((status) => (
                          <SelectItem key={status.id} value={String(status.id)}>
                            {status.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label={t("stream.activeLabel")}>
                    <Select
                      value={statusOption(binding.active_status_id)}
                      disabled={busy || statuses.length === 0}
                      onValueChange={(value) => save({ active_status_id: statusValue(value) })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE}>{t("stream.noStatusRole")}</SelectItem>
                        {statuses.map((status) => (
                          <SelectItem key={status.id} value={String(status.id)}>
                            {status.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                </div>
                <p className="text-muted-foreground text-xs">
                  {binding.awaiting_filer_status_id
                    ? t("stream.statusRolesHelp")
                    : t("stream.noAwaitingHelp")}
                </p>
              </div>
            ) : null}

            {binding.shares_initiative ? (
              <p className="text-destructive text-sm">
                {t(binding.isolated ? "stream.sharesIsolated" : "stream.sharesWithIsolated")}
              </p>
            ) : null}

            <div className="flex items-center gap-3 border-t pt-4">
              <Switch
                id={`enabled-${stream}`}
                checked={binding.enabled}
                disabled={busy}
                onCheckedChange={(checked) => save({ enabled: Boolean(checked) })}
              />
              <Label htmlFor={`enabled-${stream}`}>{t("stream.enabledLabel")}</Label>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
              <p className="text-muted-foreground text-sm">
                {binding.last_case_at
                  ? t("stream.lastCase", { when: formatDateTime(binding.last_case_at) })
                  : t("stream.noCasesYet")}
              </p>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setUnbinding(true)}>
                {t("stream.unbind")}
              </Button>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={unbinding}
          onOpenChange={setUnbinding}
          title={t("stream.unbindTitle")}
          description={t("stream.unbindBody")}
          confirmLabel={t("stream.unbindConfirm")}
          onConfirm={() => remove.mutate(stream)}
        />
      </CardContent>
    </Card>
  );
};
