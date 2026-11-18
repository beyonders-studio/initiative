/**
 * Sending somebody something: a line in their bell that opens it, on whichever
 * device they tap it, with a note if there is one.
 *
 * The people of the thing's initiative are offered. Whoever can't open it yet
 * is let in by a sender who may share it, at the rung chosen here; otherwise
 * the line tells them it is there, and opening it offers to ask for access.
 * The server decides who is which and refuses anybody it may not tell.
 */

import { Eye, MessageCircleQuestion, Pencil, Send, X } from "lucide-react";
import { type FormEvent, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContentKind, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { MemberAvatar, type MemberLike } from "@/components/members/MemberSearchSelect";
import { useAuth } from "@/hooks/useAuth";
import { useSendTo, useShareStanding } from "@/hooks/useShareRequests";
import { type MemberSearchScope, useMemberSearch } from "@/hooks/useUsers";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** Mirrors the backend's limit on a send's note, which is the authority. */
const NOTE_MAX_LENGTH = 1000;

/** What somebody who can't open it yet gets: let in to view or edit, or told
 *  it is there to ask for. */
type LetIn = "read" | "write" | "ask";

interface SendTarget {
  kind: ContentKind;
  entityId: number;
}

/** "Send to…" on anything with a page of its own, beside its subscribe bell. */
export const SendButton = ({ kind, entityId, className }: SendTarget & { className?: string }) => {
  const { t } = useTranslation("access");
  const [open, setOpen] = useState(false);
  const label = t("send.button");

  return (
    <>
      <button
        type="button"
        className={cn(
          "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className
        )}
        aria-label={label}
        title={label}
        onClick={() => setOpen(true)}
      >
        <Send className="size-5" aria-hidden />
      </button>
      {open ? (
        <SendToDialog open={open} onOpenChange={setOpen} kind={kind} entityId={entityId} />
      ) : null}
    </>
  );
};

const COMMUNITY_SCOPE: MemberSearchScope = { type: "community" };

export const SendToDialog = ({ open, onOpenChange, kind, entityId }: DialogProps & SendTarget) => {
  const { t } = useTranslation("access");
  const id = useId();
  const { user } = useAuth();
  // The tool that decides it, where the sender stands on it, and its
  // initiative: whose people are offered.
  const standing = useShareStanding(kind as SearchEntityType, entityId);
  const initiativeId = standing.data?.initiative_id;
  const mayLetIn = standing.data?.level === "owner";

  const [chosen, setChosen] = useState<MemberLike[]>([]);
  const [query, setQuery] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [note, setNote] = useState("");
  const [letIn, setLetIn] = useState<LetIn>("read");

  const scope = useMemo<MemberSearchScope>(
    () => (initiativeId != null ? { type: "initiative", initiativeId } : COMMUNITY_SCOPE),
    [initiativeId]
  );
  const search = useMemberSearch(scope, { search: query, enabled: pickerOpen });
  const offered = useMemo(
    () =>
      (search.data?.items ?? []).filter(
        (member) => member.id !== user?.id && !chosen.some((c) => c.id === member.id)
      ),
    [search.data, user?.id, chosen]
  );

  const sendTo = useSendTo({
    onSuccess: (result) => {
      toast.success(
        result.may_ask.length > 0
          ? t("send.sentSomeMayAsk", { count: result.may_ask.length })
          : t("send.sent")
      );
      onOpenChange(false);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    sendTo.mutate({
      kind,
      entity_id: entityId,
      user_ids: chosen.map((member) => member.id),
      note: note.trim() || null,
      level: mayLetIn && letIn !== "ask" ? letIn : null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("send.title")}</DialogTitle>
          <DialogDescription>{t("send.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-2">
            <Label htmlFor={`${id}-people`}>{t("send.people")}</Label>
            {chosen.length > 0 ? (
              <ul className="flex flex-wrap gap-2">
                {chosen.map((member) => (
                  <li
                    key={member.id}
                    className="flex items-center gap-1.5 rounded-full border py-0.5 pr-1 pl-0.5 text-sm"
                  >
                    <MemberAvatar user={member} />
                    {getUserDisplayName(member)}
                    <button
                      type="button"
                      className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label={t("send.remove", { name: getUserDisplayName(member) })}
                      onClick={() => setChosen((all) => all.filter((c) => c.id !== member.id))}
                    >
                      <X className="size-3.5" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <Combobox
              id={`${id}-people`}
              items={offered.map((member) => ({
                value: String(member.id),
                label: getUserDisplayName(member),
                sublabel: member.display_name?.trim() ? getUserHandle(member) : undefined,
              }))}
              onValueChange={(value) => {
                const member = offered.find((m) => m.id === Number(value));
                if (member) setChosen((all) => [...all, member]);
              }}
              onSearchChange={setQuery}
              onOpenChange={setPickerOpen}
              loading={search.isFetching && offered.length === 0}
              placeholder={t("send.addPeople")}
              searchPlaceholder={t("share.searchPeople")}
              emptyMessage={t("share.noPeople")}
              disabled={sendTo.isPending}
            />
          </div>
          {mayLetIn ? (
            <div className="space-y-2">
              <Label id={`${id}-let-in`}>{t("send.letIn")}</Label>
              <ToggleGroup
                type="single"
                variant="outline"
                value={letIn}
                onValueChange={(next) => {
                  if (next) setLetIn(next as LetIn);
                }}
                aria-labelledby={`${id}-let-in`}
                className="flex-wrap justify-start"
                disabled={sendTo.isPending}
              >
                <ToggleGroupItem value="read" className="px-3">
                  <Eye />
                  {t("request.view")}
                </ToggleGroupItem>
                <ToggleGroupItem value="write" className="px-3">
                  <Pencil />
                  {t("request.edit")}
                </ToggleGroupItem>
                <ToggleGroupItem value="ask" className="px-3">
                  <MessageCircleQuestion />
                  {t("send.letAsk")}
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
          ) : null}
          <Field label={t("request.note")}>
            <Textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={t("request.notePlaceholder")}
              maxLength={NOTE_MAX_LENGTH}
              rows={3}
              disabled={sendTo.isPending}
            />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" pending={sendTo.isPending} disabled={chosen.length === 0}>
              <Send />
              {t("send.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
};
