import { type FormEvent, useMemo, useState } from "react";
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
  useUpdateIntakeStreamContact,
  useUpsertIntakeBinding,
} from "@/hooks/useIntakeSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
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
import { formatDateTime } from "@/ui/lib/formatDate";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Sentinel for "none", which a Select cannot express with "". */
export const NONE = "none";

/**
 * The whole binding a PUT replaces, with `changes` over what is stored. The
 * row's switch and the dialog's Save both send one.
 */
export const bindingBody = (
  binding: IntakeBindingRead,
  changes: Partial<IntakeBindingUpsert> = {}
): IntakeBindingUpsert => ({
  project_id: binding.project_id as number,
  default_status_id: binding.default_status_id ?? null,
  task_type_id: binding.task_type_id ?? null,
  awaiting_filer_status_id: binding.awaiting_filer_status_id ?? null,
  active_status_id: binding.active_status_id ?? null,
  enabled: binding.enabled,
  ...changes,
});

interface StreamDialogProps {
  binding: IntakeBindingRead;
  /** Who to contact about this kind of case, as saved. */
  contact: string;
  /** The operations community is named, so the stream can be routed. */
  routable: boolean;
  initiatives: IntakeInitiativeOption[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * One stream's settings: who to contact about its cases and, once there is an
 * operations community, where they land. An unrouted stream is set up here,
 * from its blueprint or onto a project that exists; a routed one changes its
 * project, the status and type new cases take, the conversation's two statuses,
 * and stops routing.
 */
export const StreamDialog = ({
  binding,
  contact,
  routable,
  initiatives,
  open,
  onOpenChange,
}: StreamDialogProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t(`streams.${stream}.title`)}</DialogTitle>
          <DialogDescription>{t(`streams.${stream}.description`)}</DialogDescription>
        </DialogHeader>
        {/* Remounted once the stream lands somewhere new, so the form starts
            from what that project offers. */}
        <StreamForm
          key={binding.project_id ?? NONE}
          binding={binding}
          contact={contact}
          routable={routable}
          initiatives={initiatives}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
};

const StreamForm = ({
  binding,
  contact,
  routable,
  initiatives,
  onDone,
}: Omit<StreamDialogProps, "open" | "onOpenChange"> & { onDone: () => void }) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;
  const ideas = stream === "ideas";
  const filed = binding.filed !== false;
  const bound = binding.project_id !== null;

  const [initiativeId, setInitiativeId] = useState("");
  const [unbinding, setUnbinding] = useState(false);
  const [email, setEmail] = useState(contact);
  const [projectId, setProjectId] = useState(binding.project_id);
  const [defaultStatusId, setDefaultStatusId] = useState(binding.default_status_id ?? null);
  const [taskTypeId, setTaskTypeId] = useState(binding.task_type_id ?? null);
  const [awaitingId, setAwaitingId] = useState(binding.awaiting_filer_status_id ?? null);
  const [activeId, setActiveId] = useState(binding.active_status_id ?? null);

  const importBlueprint = useImportIntakeBlueprint({
    onSuccess: (result) => toast.success(t("stream.createdToast", { name: result.project_name })),
  });
  const upsert = useUpsertIntakeBinding();
  const updateContact = useUpdateIntakeStreamContact();
  const remove = useDeleteIntakeBinding({
    onSuccess: () => {
      toast.success(t("stream.unboundToast"));
      onDone();
    },
  });
  const busy =
    importBlueprint.isPending || upsert.isPending || updateContact.isPending || remove.isPending;

  // Every project in the community, flattened, labelled by its initiative —
  // the picker is a list of destinations, and the initiative is context on
  // each rather than a second choice to make first.
  const projects = useMemo(
    () =>
      initiatives.flatMap((initiative) =>
        initiative.projects.map((project) => ({ ...project, initiativeName: initiative.name }))
      ),
    [initiatives]
  );
  const chosen = projects.find((project) => project.id === projectId);
  const statuses = chosen?.statuses ?? [];
  const types = chosen?.task_types ?? [];
  const repointed = bound && projectId !== binding.project_id;

  const option = (id: number | null) => (id ? String(id) : NONE);
  const idOf = (value: string) => (value === NONE ? null : Number(value));

  const contactChanged = filed && email.trim() !== contact;
  const routingChanged =
    bound &&
    (projectId !== binding.project_id ||
      defaultStatusId !== (binding.default_status_id ?? null) ||
      taskTypeId !== (binding.task_type_id ?? null) ||
      awaitingId !== (binding.awaiting_filer_status_id ?? null) ||
      activeId !== (binding.active_status_id ?? null));

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (contactChanged) {
      try {
        await updateContact.mutateAsync({ stream, body: { email: email.trim() || null } });
      } catch (err) {
        toast.error(getErrorMessage(err, "intake:contacts.saveError"));
        return;
      }
    }
    if (routingChanged && projectId !== null) {
      try {
        await upsert.mutateAsync({
          stream,
          body: bindingBody(binding, {
            project_id: projectId,
            default_status_id: defaultStatusId,
            task_type_id: taskTypeId,
            awaiting_filer_status_id: awaitingId,
            active_status_id: activeId,
          }),
        });
      } catch {
        // The binding's own hook has said why.
        return;
      }
    }
    toast.success(t("stream.saved"));
    onDone();
  };

  // A status picker over the chosen project's statuses, with a "none" choice.
  const statusSelect = (
    value: number | null,
    onChange: (id: number | null) => void,
    noneLabel: string
  ) => (
    <Select
      value={option(value)}
      disabled={busy || statuses.length === 0}
      onValueChange={(next) => onChange(idOf(next))}
    >
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{noneLabel}</SelectItem>
        {statuses.map((status) => (
          <SelectItem key={status.id} value={String(status.id)}>
            {status.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <form className="space-y-5" onSubmit={onSubmit}>
      {filed && (
        <Field label={t("stream.contactLabel")} hint={t("stream.contactHelp")}>
          <Input
            type="email"
            value={email}
            placeholder={t("contacts.streamPlaceholder")}
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
      )}

      {!routable ? (
        <p className="text-muted-foreground text-sm">{t("rows.chooseCommunity")}</p>
      ) : !bound ? (
        <div className="space-y-4 border-t pt-4">
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
              type="button"
              disabled={busy || !initiativeId}
              onClick={() => importBlueprint.mutate({ stream, initiativeId: Number(initiativeId) })}
            >
              {t("stream.setUpForMe")}
            </Button>
          </div>
          <Field label={t("stream.existingProjectLabel")}>
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
        <div className="space-y-4 border-t pt-4">
          {/* Repointing starts fresh in the new project: a case still open in
              the old one stays where the work on it is. */}
          <Field
            label={t("stream.landsInLabel")}
            hint={repointed ? t("stream.repointNote") : undefined}
            error={binding.project_archived && !repointed ? t("stream.archivedNote") : undefined}
          >
            <Select
              value={String(projectId)}
              disabled={busy}
              onValueChange={(value) => {
                // The statuses and type belong to the project they came from.
                setProjectId(Number(value));
                setDefaultStatusId(null);
                setTaskTypeId(null);
                setAwaitingId(null);
                setActiveId(null);
              }}
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

          <div className="grid grid-cols-pair gap-4">
            <Field label={t("stream.landingStatusLabel")}>
              {statusSelect(defaultStatusId, setDefaultStatusId, t("stream.landingStatusDefault"))}
            </Field>

            {/* A project with one type has nothing to choose, except on the
                Ideas board, where the type is what publishes an idea. */}
            {types.length > 1 || taskTypeId || ideas ? (
              <Field label={t(ideas ? "stream.ideaTypeLabel" : "stream.caseTypeLabel")}>
                <Select
                  value={option(taskTypeId)}
                  disabled={busy}
                  onValueChange={(value) => setTaskTypeId(idOf(value))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>
                      {t(ideas ? "stream.ideaTypeNone" : "stream.caseTypeDefault")}
                    </SelectItem>
                    {/* One the project no longer offers names itself, or the
                        control would render blank. */}
                    {taskTypeId && !types.some((type) => type.id === taskTypeId) ? (
                      <SelectItem value={String(taskTypeId)} disabled>
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
          </div>

          {binding.conversation && binding.conversation !== Conversation.none ? (
            <div className="space-y-2">
              <div className="grid grid-cols-pair gap-4">
                <Field label={t("stream.awaitingLabel")}>
                  {statusSelect(awaitingId, setAwaitingId, t("stream.noStatusRole"))}
                </Field>
                <Field label={t("stream.activeLabel")}>
                  {statusSelect(activeId, setActiveId, t("stream.noStatusRole"))}
                </Field>
              </div>
              <p className="text-muted-foreground text-xs">
                {awaitingId ? t("stream.statusRolesHelp") : t("stream.noAwaitingHelp")}
              </p>
            </div>
          ) : null}

          {binding.shares_initiative ? (
            <p className="text-destructive text-sm">
              {t(binding.isolated ? "stream.sharesIsolated" : "stream.sharesWithIsolated")}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
            <p className="text-muted-foreground text-sm">
              {binding.last_case_at
                ? t("stream.lastCase", { when: formatDateTime(binding.last_case_at) })
                : t("stream.noCasesYet")}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              disabled={busy}
              onClick={() => setUnbinding(true)}
            >
              {t("stream.unbind")}
            </Button>
          </div>
        </div>
      )}

      <DialogFooter
        submitLabel={t("stream.save")}
        pendingLabel={t("stream.saving")}
        pending={updateContact.isPending || upsert.isPending}
        disabled={!contactChanged && !routingChanged}
      />

      <ConfirmDialog
        open={unbinding}
        onOpenChange={setUnbinding}
        title={t("stream.unbindTitle")}
        description={t("stream.unbindBody")}
        confirmLabel={t("stream.unbindConfirm")}
        onConfirm={() => remove.mutate(stream)}
      />
    </form>
  );
};
