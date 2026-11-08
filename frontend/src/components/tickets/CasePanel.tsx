/**
 * How an operations case was filed, on the task the team works it in.
 *
 * Who filed it and what they called it, and — where the case's stream holds a
 * conversation with them — that conversation and a way to answer it. It is
 * kept apart from the task's comments: everything here is what the requester
 * reads, and nothing in the thread below ever reaches them. A published idea
 * is a case nobody filed: it shows how many voted for it.
 */
import { Link } from "@tanstack/react-router";
import { Inbox, KeyRound, Lightbulb, Send, UserCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type AccessGrantRead,
  type CaseEvidenceRead,
  type CaseMessageRead,
  CommentAudience,
  Conversation,
  type TaskCaseRead,
} from "@/api/generated/initiativeAPI.schemas";
import { AccessGrantStatusBadge } from "@/components/access/AccessGrantStatusBadge";
import { CommentContent } from "@/components/comments/CommentContent";
import { UserHandle } from "@/components/user/UserHandle";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCreateComment } from "@/hooks/useComments";
import { useCreateTask, useTasks, useUpdateTask } from "@/hooks/useTasks";
import {
  refreshTaskCase,
  useJoinCaseToIdea,
  useJoinIdeaInto,
  useTakeCase,
  useTaskCase,
} from "@/hooks/useTickets";
import { Capability, hasCapability } from "@/lib/permissions";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { Combobox } from "@/ui/combobox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { minutesLeft } from "@/ui/lib/formatDate";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";

import { CaseHolds } from "./CaseHolds";
import { communityEvidenceUrl, EvidenceList } from "./Evidence";

interface CasePanelProps {
  taskId: number;
  /** Whether the reader may change the task. */
  canEdit: boolean;
  /** Who the task is assigned to, so the reader can take it if they aren't. */
  assigneeIds: number[];
}

const Message = ({
  message,
  evidence,
  urlFor,
}: {
  message: CaseMessageRead;
  evidence: CaseEvidenceRead[];
  urlFor: (evidenceId: number) => string;
}) => {
  const { t } = useTranslation("intake");
  const when = useRelativeTime(message.created_at);
  const name = message.author ? getUserDisplayName(message.author) : t("case.someone");
  return (
    <li className={cn("flex", message.from_requester ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg border px-3 py-2",
          message.from_requester ? "bg-muted/40" : "border-primary/30 bg-primary/5"
        )}
      >
        <p className="mb-1 text-muted-foreground text-xs">
          {message.from_requester ? name : t("case.fromTeam", { name })} · {when}
        </p>
        <div className="text-sm">
          <CommentContent content={message.content} />
        </div>
        <EvidenceList className="mt-2" items={evidence} urlFor={urlFor} blurred />
      </div>
    </li>
  );
};

/** What a grant reaches and how far, in the words the request form uses. */
const GRANT_LEVEL_KEY: Partial<
  Record<
    string,
    "levelRead" | "levelReadWrite" | "levelModerate" | "levelAdmin" | "levelSuperadmin"
  >
> = {
  read: "levelRead",
  read_write: "levelReadWrite",
  moderate: "levelModerate",
  admin: "levelAdmin",
  superadmin: "levelSuperadmin",
};

const GrantRow = ({ grant }: { grant: AccessGrantRead }) => {
  const { t } = useTranslation(["intake", "settings"]);
  const left = grant.is_live ? minutesLeft(grant.expires_at) : null;
  const purpose = t(
    grant.purpose === "settings"
      ? "settings:accessGrants.purposeSettings"
      : "settings:accessGrants.purposeContent"
  );
  const levelKey = GRANT_LEVEL_KEY[grant.access_level];
  const level = levelKey ? t(`settings:accessGrants.${levelKey}`) : grant.access_level;
  const community = grant.community_name
    ? `${grant.community_name} (#${grant.community_id})`
    : `#${grant.community_id}`;
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm">
          {grant.user ? (
            <UserHandle user={grant.user} />
          ) : (
            getUserDisplayName({ id: grant.user_id })
          )}{" "}
          → {community}
        </p>
        <p className="text-muted-foreground text-xs">
          {purpose} · {level}
          {left !== null ? <> · {t("case.access.endsIn", { minutes: left })}</> : null}
        </p>
      </div>
      <AccessGrantStatusBadge grant={grant} />
    </li>
  );
};

/**
 * The access asked for on this case, and a way to ask for more. The request
 * form opens with this case chosen, and the community it is about where it
 * names one.
 */
const CaseAccess = ({
  taskId,
  grants,
  subjectCommunityId,
}: {
  taskId: number;
  grants: AccessGrantRead[];
  subjectCommunityId: number | null;
}) => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const canRequest = hasCapability(user, Capability.accessRequest);
  if (grants.length === 0 && !canRequest) return null;
  // A grant on the same community already carries its name, which saves the
  // picker showing a bare number.
  const subjectName =
    subjectCommunityId == null
      ? null
      : (grants.find((grant) => grant.community_id === subjectCommunityId)?.community_name ?? null);
  return (
    <CardContent className="space-y-2 border-t pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-medium text-sm">
          <KeyRound className="h-4 w-4" aria-hidden="true" />
          {t("case.access.title")}
        </p>
        {canRequest ? (
          <Button asChild variant="outline" size="sm">
            <Link
              to="/settings/operator/access"
              search={{
                form: "request",
                case: taskId,
                ...(subjectCommunityId == null ? {} : { community: subjectCommunityId }),
                ...(subjectName ? { name: subjectName } : {}),
              }}
            >
              {t("case.access.request")}
            </Link>
          </Button>
        ) : null}
      </div>
      {grants.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("case.access.none")}</p>
      ) : (
        <ul className="divide-y" aria-label={t("case.access.listLabel")}>
          {grants.map((grant) => (
            <GrantRow key={grant.id} grant={grant} />
          ))}
        </ul>
      )}
    </CardContent>
  );
};

/**
 * Where a case joins an idea on the Ideas board. Feedback joins one, picked
 * from the board or made from what is typed, and whoever sent it gets a vote;
 * an idea joins another, which takes its votes and feedback and archives it.
 */
const CaseIdea = ({
  taskId,
  found,
  canEdit,
}: {
  taskId: number;
  found: TaskCaseRead;
  canEdit: boolean;
}) => {
  const { t } = useTranslation(["intake", "common"]);
  const communityId = useActiveCommunityId();
  const board = found.ideas_board_id ?? null;
  const isIdea = found.votes != null;
  const [search, setSearch] = useState("");
  const [into, setInto] = useState<{ id: number; title: string } | null>(null);
  const join = useJoinCaseToIdea(taskId);
  const joinInto = useJoinIdeaInto(taskId, { onSuccess: () => setInto(null) });
  const createTask = useCreateTask();
  const ideas = useTasks(
    {
      conditions: [
        { field: "project_id", op: "eq", value: board },
        ...(search ? [{ field: "title", op: "ilike" as const, value: search }] : []),
      ],
      page_size: 20,
    },
    { enabled: board != null && canEdit }
  );
  if (board == null) return null;
  const items = (ideas.data?.items ?? [])
    .filter((task) => task.id !== taskId)
    .map((task) => ({ value: String(task.id), label: task.title }));
  const titleOf = (value: string) => items.find((item) => item.value === value)?.label ?? "";
  const pending = join.isPending || joinInto.isPending || createTask.isPending;
  const joined = found.joined_idea;

  const picker = (placeholder: string, onPick: (value: string) => void, create: boolean) => (
    <Combobox
      items={items}
      value={null}
      onValueChange={onPick}
      onSearchChange={setSearch}
      loading={ideas.isFetching}
      placeholder={placeholder}
      searchPlaceholder={t("case.idea.search")}
      emptyMessage={t("case.idea.none")}
      disabled={pending}
      {...(create
        ? {
            typedLabel: (typed: string) => t("case.idea.create", { title: typed }),
            onCreate: async (typed: string) => {
              const made = await createTask.mutateAsync({ project_id: board, title: typed });
              join.mutate(made.id);
            },
          }
        : {})}
    />
  );

  return (
    <CardContent className="space-y-2 border-t pt-4">
      <p className="flex items-center gap-2 font-medium text-sm">
        <Lightbulb className="h-4 w-4" aria-hidden="true" />
        {t("case.idea.title")}
      </p>
      {isIdea ? (
        canEdit ? (
          <>
            {picker(
              t("case.idea.joinInto"),
              (value) => setInto({ id: Number(value), title: titleOf(value) }),
              false
            )}
            <ConfirmDialog
              open={into != null}
              onOpenChange={(open) => (open ? null : setInto(null))}
              title={t("case.idea.joinIntoTitle", { title: into?.title ?? "" })}
              description={t("case.idea.joinIntoBody", { title: into?.title ?? "" })}
              confirmLabel={t("case.idea.joinIntoConfirm")}
              isLoading={joinInto.isPending}
              onConfirm={() => into && joinInto.mutate(into.id)}
            />
          </>
        ) : null
      ) : joined ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            to="/c/$communityId/go/$refType/$refId"
            params={{
              communityId: String(communityId),
              refType: "task",
              refId: String(joined.task_id),
            }}
            className="min-w-0 font-medium text-sm hover:underline"
          >
            {joined.title}
          </Link>
          {canEdit ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={pending}
              onClick={() => join.mutate(null)}
            >
              {t("case.idea.unjoin")}
            </Button>
          ) : null}
        </div>
      ) : canEdit ? (
        picker(t("case.idea.join"), (value) => join.mutate(Number(value)), true)
      ) : (
        <p className="text-muted-foreground text-sm">{t("case.idea.notJoined")}</p>
      )}
      <p className="text-muted-foreground text-xs">
        {t(isIdea ? "case.idea.joinIntoHelp" : "case.idea.help")}
      </p>
    </CardContent>
  );
};

export const CasePanel = ({ taskId, canEdit, assigneeIds }: CasePanelProps) => {
  const { t } = useTranslation(["intake", "common"]);
  const { user } = useAuth();
  const caseQuery = useTaskCase(taskId);
  const takeCase = useTakeCase();
  const communityId = useActiveCommunityId();
  const [reply, setReply] = useState("");
  const createComment = useCreateComment();
  const updateTask = useUpdateTask();
  const filed = useRelativeTime(caseQuery.data?.opened_at ?? null);

  // A 404 keeps the last answer cached: a published idea put back to a draft
  // is no longer a case, though it was one a moment ago.
  const found = caseQuery.isError ? undefined : caseQuery.data;
  if (!found) return null;

  const filerName = found.filer ? getUserDisplayName(found.filer) : null;
  // A published idea: the board's, not a ticket somebody takes or asks access for.
  const idea = found.votes != null;
  const mine = user != null && assigneeIds.includes(user.id);
  const awaiting = found.awaiting_filer_status_id ?? null;
  const messages = found.messages ?? [];
  const teamHasSpoken = messages.some((message) => !message.from_requester);
  const pending = createComment.isPending || updateTask.isPending;
  const evidence = found.evidence ?? [];
  const shownIds = new Set(messages.map((message) => message.id));
  // Files beside no message shown here: carried in with a report, or sent
  // with words the conversation no longer holds.
  const loose = evidence.filter(
    (item) => item.comment_id == null || !shownIds.has(item.comment_id)
  );
  const urlFor = (evidenceId: number) => communityEvidenceUrl(communityId, evidenceId);

  const send = async (wait: boolean) => {
    const content = reply.trim();
    if (!content) return;
    await createComment.mutateAsync({
      content,
      task_id: taskId,
      audience: CommentAudience.filer,
    });
    setReply("");
    void refreshTaskCase(taskId);
    if (wait && awaiting != null) {
      await updateTask.mutateAsync({ taskId, data: { task_status_id: awaiting } });
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Inbox className="h-4 w-4" aria-hidden="true" />
          {t(`streams.${found.stream}.title`)}
          {/* What the filer said it is about, where they chose. */}
          {found.topic ? (
            <span className="font-normal text-muted-foreground">
              · {t(`case.topics.${found.topic}`, { defaultValue: found.topic })}
            </span>
          ) : null}
        </CardTitle>
        <p className="text-muted-foreground text-sm">
          {idea ? (
            <>{t("case.votes", { count: found.votes })} · </>
          ) : filerName ? (
            <>
              {t("case.filedBy")}{" "}
              <UserHoverLink user={found.filer ?? null} className="font-medium text-foreground">
                {filerName}
              </UserHoverLink>
              {" · "}
            </>
          ) : (
            // Feedback has no filer where its sender did not offer to be contacted.
            <>{t(found.stream === "feedback" ? "case.noContact" : "case.noFiler")} · </>
          )}
          {filed}
        </p>
        {found.filer_subject ? (
          <p className="text-sm">
            <span className="text-muted-foreground">{t("case.theyCalledIt")}</span>{" "}
            {found.filer_subject}
          </p>
        ) : null}
        {idea ? null : mine ? (
          <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
            <UserCheck className="h-4 w-4" aria-hidden="true" />
            {t("case.taken")}
          </p>
        ) : canEdit ? (
          <div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={takeCase.isPending}
              onClick={() => takeCase.mutate(taskId)}
            >
              <UserCheck className="h-4 w-4" aria-hidden="true" />
              {t("case.take")}
            </Button>
          </div>
        ) : null}
      </CardHeader>
      {loose.length > 0 ? (
        <CardContent className="space-y-2 pb-3">
          <p className="font-medium text-muted-foreground text-xs">{t("evidence.heading")}</p>
          <EvidenceList items={loose} urlFor={urlFor} blurred />
        </CardContent>
      ) : null}
      {found.stream === "moderation" && found.subject_community_id != null ? (
        <CaseHolds
          taskId={taskId}
          communityId={found.subject_community_id}
          resourceType={found.resource_type}
          resourceId={found.resource_id}
        />
      ) : null}
      <CaseIdea taskId={taskId} found={found} canEdit={canEdit} />
      {idea ? null : (
        <CaseAccess
          taskId={taskId}
          grants={found.grants ?? []}
          subjectCommunityId={found.subject_community_id ?? null}
        />
      )}
      {found.filer && (
        <CardContent className="space-y-3">
          {messages.length > 0 ? (
            <ul className="space-y-3" aria-label={t("case.conversationLabel", { name: filerName })}>
              {messages.map((message) => (
                <Message
                  key={message.id}
                  message={message}
                  evidence={evidence.filter((item) => item.comment_id === message.id)}
                  urlFor={urlFor}
                />
              ))}
            </ul>
          ) : null}
          {found.conversation === Conversation.none ? (
            <p className="text-muted-foreground text-sm">{t("case.noConversation")}</p>
          ) : (
            <>
              {found.conversation === Conversation.staff_first && !teamHasSpoken ? (
                <p className="text-muted-foreground text-sm">{t("case.staffFirst")}</p>
              ) : null}
              <Textarea
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder={t("case.replyPlaceholder", { name: filerName })}
                aria-label={t("case.replyLabel", { name: filerName })}
                rows={3}
                disabled={!canEdit || pending}
              />
              <p className="text-muted-foreground text-xs">{t("case.replyHelp")}</p>
              <div className="flex flex-wrap justify-end gap-2">
                {awaiting != null ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!canEdit || pending || !reply.trim()}
                    onClick={() => void send(true)}
                  >
                    {t("case.replyAndWait")}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  disabled={!canEdit || pending || !reply.trim()}
                  onClick={() => void send(false)}
                >
                  <Send className="h-4 w-4" aria-hidden="true" />
                  {t("case.reply")}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
};
