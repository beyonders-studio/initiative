/**
 * Answering access requests: on the thing's own Access settings, every
 * request for it; on a request's own page, everything one ask asked for.
 *
 * Share gives the level asked for unless the answerer picks another, to the
 * person or to everyone in the initiative. Decline tells the person only when
 * the answerer says to.
 */

import { Link } from "@tanstack/react-router";
import { Check, Loader2, X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ResourceAccessLevel,
  ShareRequestRead,
  ShareRequestScope,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RelativeTime } from "@/components/ui/relative-time";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type ShareRequestReply,
  useAnswerShareRequests,
  useShareRequests,
} from "@/hooks/useShareRequests";
import { useCommunityPath } from "@/lib/communityUrl";
import { dateTimeFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import { entityRefRoute, TOOL_ICONS, toolKebabSingular } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";

type GiveLevel = Exclude<ResourceAccessLevel, "owner">;

/** What an answer gives: the level, to whom, and whether a no is told. */
interface Answer {
  level: GiveLevel;
  scope: ShareRequestScope;
  tell: boolean;
}

const askedLevel = (request: ShareRequestRead | undefined): GiveLevel =>
  request?.level === "write" ? "write" : "read";

/** Answers requests, saying so once the server has them. */
const useAnswer = () => {
  const { t } = useTranslation("access");
  return useAnswerShareRequests({
    onSuccess: (_, { approve }) =>
      toast.success(approve ? t("answer.shared") : t("answer.declined")),
  });
};

/** Who asked: their picture and name, how long they are a guest for, when. */
const Requester = ({ request }: { request: ShareRequestRead }) => {
  const { t, i18n } = useTranslation("access");
  const name = getUserDisplayName(request.user, t("answer.someone"));
  const avatarSrc = getAvatarSrc(request.user);
  return (
    <div className="flex min-w-0 items-start gap-3">
      <Avatar className="h-8 w-8 shrink-0">
        {avatarSrc ? <AvatarImage src={avatarSrc} alt={name} /> : null}
        <AvatarFallback
          userId={isAnonymizedUser(request.user) ? null : request.user.id}
          className="text-xs"
        >
          {getInitialsForUser(request.user)}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-medium text-sm">{name}</span>
          <span className="text-muted-foreground text-sm">
            {request.level === "write" ? t("answer.asksEdit") : t("answer.asksView")}
          </span>
          <RelativeTime
            date={request.created_at}
            className="shrink-0 text-muted-foreground text-xs"
          />
          {request.guest_until ? (
            <Badge variant="outline" className="font-normal text-xs">
              {t("answer.guestUntil", {
                date: dateTimeFormat(i18n.language, { dateStyle: "medium" }).format(
                  new Date(request.guest_until)
                ),
              })}
            </Badge>
          ) : null}
        </div>
        {request.message ? (
          <p className="wrap-break-word whitespace-pre-wrap text-muted-foreground text-sm">
            {request.message}
          </p>
        ) : null}
      </div>
    </div>
  );
};

/** The level and who it reaches. */
const AnswerFields = ({
  value,
  onChange,
  disabled,
}: {
  value: Answer;
  onChange: (next: Answer) => void;
  disabled: boolean;
}) => {
  const { t } = useTranslation("access");
  const id = useId();
  return (
    <div className="flex flex-wrap gap-3">
      <div className="space-y-1">
        <Label htmlFor={`${id}-level`} className="text-muted-foreground text-xs">
          {t("answer.level")}
        </Label>
        <Select
          value={value.level}
          onValueChange={(level) => onChange({ ...value, level: level as GiveLevel })}
          disabled={disabled}
        >
          <SelectTrigger id={`${id}-level`} className="h-8 w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="read">{t("request.view")}</SelectItem>
            <SelectItem value="write">{t("request.edit")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-scope`} className="text-muted-foreground text-xs">
          {t("answer.scope")}
        </Label>
        <Select
          value={value.scope}
          onValueChange={(scope) => onChange({ ...value, scope: scope as ShareRequestScope })}
          disabled={disabled}
        >
          <SelectTrigger id={`${id}-scope`} className="h-8 w-56 max-w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="user">{t("answer.scopeUser")}</SelectItem>
            <SelectItem value="initiative">{t("answer.scopeInitiative")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
};

/** "Tell them", then Decline and Share — the answer's two buttons. */
const AnswerButtons = ({
  value,
  onChange,
  onAnswer,
  pending,
  many = false,
}: {
  value: Answer;
  onChange: (next: Answer) => void;
  onAnswer: (approve: boolean) => void;
  pending: boolean;
  /** Answers several at once, and says so. */
  many?: boolean;
}) => {
  const { t } = useTranslation("access");
  const id = useId();
  return (
    <div className="flex flex-wrap items-center justify-end gap-3">
      <div className="flex items-center gap-2">
        <Checkbox
          id={`${id}-tell`}
          checked={value.tell}
          onCheckedChange={(checked) => onChange({ ...value, tell: checked === true })}
          disabled={pending}
        />
        <Label htmlFor={`${id}-tell`} className="font-normal text-sm">
          {t("answer.tell")}
        </Label>
      </div>
      <Button variant="outline" size="sm" disabled={pending} onClick={() => onAnswer(false)}>
        <X />
        {many ? t("answer.declineAll") : t("answer.decline")}
      </Button>
      <Button size="sm" disabled={pending} onClick={() => onAnswer(true)}>
        {pending ? <Loader2 className="animate-spin" /> : <Check />}
        {many ? t("answer.shareAll") : t("answer.share")}
      </Button>
    </div>
  );
};

const reply = (requests: ShareRequestRead[], approve: boolean, answer: Answer) =>
  ({
    requests,
    approve,
    level: approve ? answer.level : null,
    scope: answer.scope,
    tell: answer.tell,
  }) satisfies ShareRequestReply;

/** One request on the thing's Access settings, with its own answer. */
const RequestRow = ({ request }: { request: ShareRequestRead }) => {
  const answer = useAnswer();
  const [value, setValue] = useState<Answer>({
    level: askedLevel(request),
    scope: "user",
    tell: false,
  });
  return (
    <li className="space-y-3 p-4">
      <Requester request={request} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AnswerFields value={value} onChange={setValue} disabled={answer.isPending} />
        <AnswerButtons
          value={value}
          onChange={setValue}
          pending={answer.isPending}
          onAnswer={(approve) => answer.mutate(reply([request], approve, value))}
        />
      </div>
    </li>
  );
};

/**
 * The requests for one thing, above who it is shared with. Nothing at all
 * when there are none — the normal state.
 */
export const ShareRequestsCard = ({ tool, entityId }: { tool: Tool; entityId: number }) => {
  const { t } = useTranslation("access");
  const { data: requests = [] } = useShareRequests({
    resource_type: tool,
    resource_id: entityId,
  });
  if (requests.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {t("answer.title")}
          <Badge variant="secondary">{requests.length}</Badge>
        </CardTitle>
        <CardDescription>{t("answer.description")}</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y">
          {requests.map((request) => (
            <RequestRow key={request.id} request={request} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
};

/**
 * Everything one ask asked for, each by name, with one answer for all of
 * them and a quicker one for each. Once nothing is left, it says so.
 */
export const ShareRequestBatchView = ({ batchId }: { batchId: string }) => {
  const { t } = useTranslation("access");
  const gp = useCommunityPath();
  const query = useShareRequests({ batch_id: batchId });
  const requests = query.data ?? [];
  const answer = useAnswer();
  const [value, setValue] = useState<Answer | null>(null);
  // The asked level, until the answerer picks another.
  const current: Answer = value ?? { level: askedLevel(requests[0]), scope: "user", tell: false };
  const answering = answer.isPending ? answer.variables?.requests : undefined;

  if (query.isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2
          className="size-5 animate-spin text-muted-foreground"
          aria-label={t("answer.loading")}
        />
      </div>
    );
  }
  if (query.isError) {
    return <p className="text-destructive text-sm">{t("answer.loadError")}</p>;
  }
  if (requests.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("answer.answered")}</CardTitle>
          <CardDescription>{t("answer.answeredDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const many = requests.length > 1;
  return (
    <Card>
      <CardHeader>
        <Requester request={requests[0]} />
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="divide-y rounded-md border">
          {requests.map((request) => {
            const Icon = TOOL_ICONS[request.resource_type];
            const busy = answering?.some((row) => row.id === request.id) ?? false;
            return (
              <li key={request.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <Link
                  to={gp(
                    entityRefRoute(toolKebabSingular(request.resource_type), request.resource_id)
                  )}
                  className="min-w-0 flex-1 truncate font-medium text-sm hover:underline"
                >
                  {request.resource_name}
                </Link>
                {many ? (
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={answer.isPending}
                      aria-label={t("answer.declineOne", { name: request.resource_name })}
                      onClick={() => answer.mutate(reply([request], false, current))}
                    >
                      <X />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={answer.isPending}
                      aria-label={t("answer.shareOne", { name: request.resource_name })}
                      onClick={() => answer.mutate(reply([request], true, current))}
                    >
                      {busy ? <Loader2 className="animate-spin" /> : <Check />}
                    </Button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <AnswerFields value={current} onChange={setValue} disabled={answer.isPending} />
          <AnswerButtons
            value={current}
            onChange={setValue}
            pending={answer.isPending}
            many={many}
            onAnswer={(approve) => answer.mutate(reply(requests, approve, current))}
          />
        </div>
      </CardContent>
    </Card>
  );
};
