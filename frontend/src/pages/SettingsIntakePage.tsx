/**
 * Where this deployment's operations work lands (platform settings → Intake).
 *
 * Whether people may send feedback to the Initiative team comes first, then
 * who to contact. Both stand on their own: a deployment that routes nothing
 * anywhere still sends feedback to the team, and tells people whom to write to.
 *
 * Then two levels of decision, in the order an owner makes them: name the
 * community that receives operations work, then say which project each stream
 * lands in. Nothing below the first is offered until it is answered, because
 * every id in it belongs to that community.
 *
 * Each stream offers the same two routes: import the blueprint, which produces
 * a ready-made project, or point at a project the team already has. Both end in
 * the same binding — the blueprint is a convenience, not a different mechanism.
 */

import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Conversation,
  type IntakeBindingRead,
  type IntakeBindingUpsert,
  type IntakeInitiativeOption,
  type IntakeSettingsRead,
  type IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import {
  useDeleteIntakeBinding,
  useImportIntakeBlueprint,
  useIntakeOptions,
  useIntakeSettings,
  useUpdateFeedbackSwitch,
  useUpdateIntakeGeneralContact,
  useUpdateIntakeStreamContact,
  useUpdateOperationsCommunity,
  useUpsertIntakeBinding,
} from "@/hooks/useIntakeSettings";
import { useServerForm } from "@/hooks/useServerForm";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Combobox } from "@/ui/combobox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

/** Sentinel for "no community", which a Select cannot express with "". */
const NONE = "none";

export const SettingsIntakePage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const isOwner = hasCapability(user, Capability.configManage);

  const {
    data: settings,
    isLoading,
    isFetching: settingsFetching,
    isError: settingsFailed,
    refetch: refetchSettings,
  } = useIntakeSettings({ enabled: isOwner });
  const {
    data: options,
    isFetching: optionsFetching,
    isError: optionsFailed,
    refetch: refetchOptions,
  } = useIntakeOptions({ enabled: isOwner });
  // Searched on the server while the picker is open, rather than every
  // community on the deployment loaded up front.
  const [communitySearch, setCommunitySearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const communitiesQuery = usePlatformCommunities(
    { search: communitySearch || undefined, sort_by: "name", page_size: 25 },
    { enabled: isOwner && pickerOpen }
  );

  // The two reads describe one community between them — where each stream
  // lands, and what it could land in — so the page acts on both or neither.
  const failed = settingsFailed || optionsFailed;
  const settled = !failed && !settingsFetching && !optionsFetching;

  const [clearing, setClearing] = useState(false);

  const updateCommunity = useUpdateOperationsCommunity({
    onError: (err) => toast.error(getErrorMessage(err, "intake:community.saveError")),
  });

  if (!isOwner) {
    return <p className="text-muted-foreground text-sm">{t("ownerOnly")}</p>;
  }

  // A read that failed is a different state from a deployment that has
  // configured nothing, and says so. The picker stays out of reach until the
  // current value is known.
  if (failed) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("loadFailed.title")}</CardTitle>
          <CardDescription>{t("loadFailed.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => {
              refetchSettings();
              refetchOptions();
            }}
          >
            {t("loadFailed.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const boundCommunityId = settings?.operations_community_id ?? null;

  return (
    <div className="space-y-6">
      {settings ? <FeedbackCard enabled={settings.feedback_enabled} settled={settled} /> : null}
      {settings ? <ContactsCard settings={settings} settled={settled} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("community.title")}</CardTitle>
          <CardDescription>{t("community.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label>{t("community.label")}</Label>
          <Combobox
            className="max-w-md"
            aria-label={t("community.label")}
            value={boundCommunityId === null ? NONE : String(boundCommunityId)}
            selectedLabel={
              boundCommunityId === null
                ? t("community.none")
                : (settings?.operations_community_name ?? null)
            }
            items={[
              { value: NONE, label: t("community.none") },
              ...(communitiesQuery.data?.items ?? []).map((community) => ({
                value: String(community.id),
                label: community.name,
              })),
            ]}
            onSearchChange={setCommunitySearch}
            onOpenChange={setPickerOpen}
            loading={communitiesQuery.isFetching}
            placeholder={t("community.placeholder")}
            disabled={isLoading || !settled || updateCommunity.isPending}
            onValueChange={(value) => {
              // Clearing it stops every stream at once, so it is confirmed;
              // choosing a different one is an ordinary change.
              if (value === NONE) {
                setClearing(true);
                return;
              }
              updateCommunity.mutate({ community_id: Number(value) });
            }}
          />
          <p className="text-muted-foreground text-sm">{t("community.helpText")}</p>
        </CardContent>
      </Card>

      {boundCommunityId === null ? (
        <p className="text-muted-foreground text-sm">{t("streams.chooseCommunityFirst")}</p>
      ) : (
        <div className="space-y-4">
          {(settings?.bindings ?? []).map((binding) => (
            <StreamCard
              key={binding.stream}
              binding={binding}
              initiatives={options?.initiatives ?? []}
              settled={settled}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("community.clearTitle")}
        description={t("community.clearBody")}
        confirmLabel={t("community.clearConfirm")}
        onConfirm={() => updateCommunity.mutate({ community_id: null })}
      />
    </div>
  );
};

/** Whether people here may send feedback to the Initiative team. */
const FeedbackCard = ({ enabled, settled }: { enabled: boolean; settled: boolean }) => {
  const { t } = useTranslation("intake");
  const update = useUpdateFeedbackSwitch({
    onError: (err) => toast.error(getErrorMessage(err, "intake:feedbackSwitch.error")),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("feedbackSwitch.title")}</CardTitle>
        <CardDescription>{t("feedbackSwitch.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex items-center gap-3">
        <Switch
          id="feedback-enabled"
          checked={enabled}
          disabled={!settled || update.isPending}
          onCheckedChange={(checked) => update.mutate({ enabled: checked })}
        />
        <Label htmlFor="feedback-enabled">{t("feedbackSwitch.label")}</Label>
      </CardContent>
    </Card>
  );
};

/**
 * Who a notice tells somebody to contact: one general address, and one per
 * stream. A stream left blank uses the general address — never another
 * stream's — and with neither set the notice names nobody.
 */
const ContactsCard = ({
  settings,
  settled,
}: {
  settings: IntakeSettingsRead;
  settled: boolean;
}) => {
  const { t } = useTranslation("intake");
  // A stream nobody files into has nobody to point at an address.
  const streams = settings.bindings
    .filter((binding) => binding.filed)
    .map((binding) => binding.stream as IntakeStream);
  // One flat field per address: "general", then each stream by name.
  const contactsOf = (loaded: IntakeSettingsRead | undefined): Record<string, string> => ({
    general: loaded?.general_contact_email ?? "",
    ...Object.fromEntries(
      streams.map((stream) => [stream, loaded?.contact_emails?.[stream] ?? ""])
    ),
  });
  const saved = contactsOf(settings);
  const form = useServerForm(settings, contactsOf, "intake-contacts");
  const draft = form.values;

  const updateGeneral = useUpdateIntakeGeneralContact();
  const updateStream = useUpdateIntakeStreamContact();
  const saving = updateGeneral.isPending || updateStream.isPending;
  const changedOf = (sent: Record<string, string>, field: string) =>
    (sent[field] ?? saved[field]).trim() !== saved[field];
  const changed = Object.keys(saved).some((field) => changedOf(draft, field));

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    // What is being sent, so anything typed while this is in flight is not
    // counted as saved by it.
    const sent = draft;
    const email = (value: string) => value.trim() || null;
    try {
      if (changedOf(sent, "general")) {
        await updateGeneral.mutateAsync({ email: email(sent.general) });
      }
      for (const stream of streams) {
        if (changedOf(sent, stream)) {
          await updateStream.mutateAsync({ stream, body: { email: email(sent[stream]) } });
        }
      }
      form.settle(sent);
      toast.success(t("contacts.saved"));
    } catch (err) {
      toast.error(getErrorMessage(err, "intake:contacts.saveError"));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("contacts.title")}</CardTitle>
        <CardDescription>{t("contacts.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="max-w-md space-y-4" onSubmit={onSubmit}>
          <div className="space-y-2">
            <Label htmlFor="intake-contact-general">{t("contacts.generalLabel")}</Label>
            <Input
              id="intake-contact-general"
              type="email"
              value={draft.general}
              placeholder={t("contacts.generalPlaceholder")}
              disabled={!settled || saving}
              onChange={(event) => form.set({ general: event.target.value })}
            />
          </div>
          {streams.map((stream) => (
            <div key={stream} className="space-y-2">
              <Label htmlFor={`intake-contact-${stream}`}>{t(`streams.${stream}.title`)}</Label>
              <Input
                id={`intake-contact-${stream}`}
                type="email"
                value={draft[stream]}
                placeholder={t("contacts.streamPlaceholder")}
                disabled={!settled || saving}
                onChange={(event) => form.set({ [stream]: event.target.value })}
              />
            </div>
          ))}
          <Button type="submit" disabled={!settled || saving || !changed}>
            {saving ? t("contacts.saving") : t("contacts.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

interface StreamCardProps {
  binding: IntakeBindingRead;
  initiatives: IntakeInitiativeOption[];
  /** Both reads have settled, so bindings and options describe one community. */
  settled: boolean;
}

const StreamCard = ({ binding, initiatives, settled }: StreamCardProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;

  const [initiativeId, setInitiativeId] = useState<string>("");
  const [unbinding, setUnbinding] = useState(false);

  const importBlueprint = useImportIntakeBlueprint({
    onSuccess: (result) => toast.success(t("stream.createdToast", { name: result.project_name })),
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const upsert = useUpsertIntakeBinding({
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const remove = useDeleteIntakeBinding({
    onSuccess: () => toast.success(t("stream.unboundToast")),
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
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
              <div className="space-y-2">
                <Label htmlFor={`initiative-${stream}`}>{t("stream.initiativeLabel")}</Label>
                <Select value={initiativeId} onValueChange={setInitiativeId} disabled={busy}>
                  <SelectTrigger id={`initiative-${stream}`} className="w-64">
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
              </div>
              <Button
                disabled={busy || !initiativeId}
                onClick={() =>
                  importBlueprint.mutate({ stream, initiativeId: Number(initiativeId) })
                }
              >
                {t("stream.setUpForMe")}
              </Button>
            </div>
            <div className="space-y-2 border-t pt-4">
              <Label htmlFor={`project-${stream}`}>{t("stream.existingProjectLabel")}</Label>
              <Select
                value=""
                disabled={busy || projects.length === 0}
                onValueChange={(value) =>
                  upsert.mutate({ stream, body: { project_id: Number(value), enabled: true } })
                }
              >
                <SelectTrigger id={`project-${stream}`} className="max-w-md">
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
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`bound-project-${stream}`}>{t("stream.landsInLabel")}</Label>
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
                <SelectTrigger id={`bound-project-${stream}`} className="max-w-md">
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
              {binding.project_archived ? (
                <p className="text-destructive text-sm">{t("stream.archivedNote")}</p>
              ) : (
                /* Repointing starts fresh in the new project: an incident still
                   open in the old one stays where the work on it is. */
                <p className="text-muted-foreground text-xs">{t("stream.repointNote")}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor={`status-${stream}`}>{t("stream.landingStatusLabel")}</Label>
              <Select
                value={binding.default_status_id ? String(binding.default_status_id) : NONE}
                disabled={busy || statuses.length === 0}
                onValueChange={(value) => save({ default_status_id: statusValue(value) })}
              >
                <SelectTrigger id={`status-${stream}`} className="max-w-xs">
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
            </div>

            {/* A project with one type has nothing to choose. */}
            {types.length > 1 || binding.task_type_id ? (
              <div className="space-y-2">
                <Label htmlFor={`type-${stream}`}>{t("stream.caseTypeLabel")}</Label>
                <Select
                  value={statusOption(binding.task_type_id)}
                  disabled={busy}
                  onValueChange={(value) => save({ task_type_id: statusValue(value) })}
                >
                  <SelectTrigger id={`type-${stream}`} className="max-w-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>{t("stream.caseTypeDefault")}</SelectItem>
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
              </div>
            ) : null}

            {binding.conversation && binding.conversation !== Conversation.none ? (
              <div className="space-y-3">
                <div className="grid grid-cols-pair gap-3">
                  <div className="space-y-2">
                    <Label htmlFor={`awaiting-${stream}`}>{t("stream.awaitingLabel")}</Label>
                    <Select
                      value={statusOption(binding.awaiting_filer_status_id)}
                      disabled={busy || statuses.length === 0}
                      onValueChange={(value) =>
                        save({ awaiting_filer_status_id: statusValue(value) })
                      }
                    >
                      <SelectTrigger id={`awaiting-${stream}`}>
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
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={`active-${stream}`}>{t("stream.activeLabel")}</Label>
                    <Select
                      value={statusOption(binding.active_status_id)}
                      disabled={busy || statuses.length === 0}
                      onValueChange={(value) => save({ active_status_id: statusValue(value) })}
                    >
                      <SelectTrigger id={`active-${stream}`}>
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
                  </div>
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
