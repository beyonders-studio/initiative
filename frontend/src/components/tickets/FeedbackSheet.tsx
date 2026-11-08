/**
 * The feedback sheet: a short review of how the app is working for somebody,
 * from wherever they are.
 *
 * Opened by the account menu and the command palette, and drawn once by the
 * app shell. A rating out of five comes first; what they like most and what
 * they wish it did are theirs to answer or leave. They may tick that the team
 * can contact them about it. The page they are on, as its route with every id
 * left out, travels with it beside the app's version, the platform, the
 * language, the theme and the window's width, shown on asking and theirs to
 * leave out.
 *
 * On a wide screen it docks beside the page, which stays in view and in
 * reach; on a phone it is a sheet from the bottom. Closing it keeps what was
 * written until it is sent or discarded.
 *
 * Where feedback is not taken here but an address is set, the sheet is that
 * address; where there is neither, nothing offers it.
 */

import { Capacitor } from "@capacitor/core";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { useMatches } from "@tanstack/react-router";
import { Star } from "lucide-react";
import { Suspense, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { type FeedbackContext, SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import proudSvg from "@/assets/yonder/proud.svg";
import talkingSvg from "@/assets/yonder/talking.svg";
import { ScaleValue } from "@/components/properties/PropertyValueCell";
import { HelpLink } from "@/components/support/HelpLink";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { EvidencePicker } from "@/components/tickets/Evidence";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useTheme } from "@/hooks/useTheme";
import { useFileTicket, useTicketAvailability } from "@/hooks/useTickets";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Sheet, SheetContent, SheetTitle } from "@/ui/sheet";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

/** Match the column behind them, so an answer stops where the server would. */
const ANSWER_MAX = 5000;

const STARS = [1, 2, 3, 4, 5] as const;
/** A rating out of five, or none yet. */
type Rating = (typeof STARS)[number] | 0;

/** The context's fields, in the order they are shown. */
const CONTEXT_FIELDS = ["app_version", "platform", "locale", "theme", "route", "viewport"] as const;

interface Draft {
  rating: Rating;
  likes: string;
  wishes: string;
  contactable: boolean;
  withContext: boolean;
  files: File[];
}

const EMPTY_DRAFT: Draft = {
  rating: 0,
  likes: "",
  wishes: "",
  contactable: false,
  withContext: true,
  files: [],
};

// Whether the sheet is open, and what is written in it, kept outside React so
// a menu item and the command palette can open the one drawn by the shell and
// closing it keeps the draft.
let sheetOpen = false;
let draft = EMPTY_DRAFT;
const listeners = new Set<() => void>();
const setSheetOpen = (open: boolean) => {
  sheetOpen = open;
  for (const listener of listeners) listener();
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Open the feedback sheet over whatever page is showing. */
export const openFeedback = () => setSheetOpen(true);

/** Whether this server offers anywhere to send feedback: a form or an address. */
export const useFeedbackOffered = () => {
  const { data } = useTicketAvailability(null);
  const mode = data?.feedback.mode;
  return mode === "form" || (mode === "email" && Boolean(data?.feedback.contact));
};

/** A route id as a template: the pathless layout segments dropped, every id
 *  left as the parameter that names it. */
export const routeTemplate = (routeId: string): string => {
  const kept = routeId.split("/").filter((segment) => segment && !segment.startsWith("_"));
  return `/${kept.join("/")}`;
};

const useFeedbackContext = (): FeedbackContext => {
  const { i18n } = useTranslation();
  const { theme } = useTheme();
  const width = useWidthClass();
  const route = useMatches({ select: (matches) => matches.at(-1)?.routeId ?? "" });
  return {
    app_version: __APP_VERSION__,
    platform: Capacitor.getPlatform(),
    locale: i18n.language,
    theme,
    route: routeTemplate(route),
    viewport: width,
  };
};

/** The sheet, drawn once by the app shell. */
export const FeedbackHost = () => {
  const open = useSyncExternalStore(subscribe, () => sheetOpen);
  if (!open) return null;
  return (
    // Its own boundary: the first opening loads the sheet's translations.
    <Suspense fallback={null}>
      <FeedbackSheet />
    </Suspense>
  );
};

const FeedbackSheet = () => {
  const { t } = useTranslation("intake");
  const communityId = useActiveCommunityId();
  const context = useFeedbackContext();
  const { data } = useTicketAvailability(communityId);
  const wide = atLeast(useWidthClass(), "sm");
  const [form, setForm] = useState(draft);
  const [preview, setPreview] = useState<Rating>(0);
  const [seeing, setSeeing] = useState(false);
  const [sent, setSent] = useState<Rating>(0);
  const stars = useRef<HTMLDivElement>(null);
  const wishesBox = useRef<HTMLTextAreaElement>(null);
  const thanks = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    draft = form;
  }, [form]);
  useEffect(() => {
    if (sent) thanks.current?.focus();
  }, [sent]);

  const change = (next: Partial<Draft>) => setForm((current) => ({ ...current, ...next }));
  const file = useFileTicket({
    onSuccess: () => {
      setSent(form.rating);
      setForm(EMPTY_DRAFT);
    },
    onError: (err) => toast.error(getErrorMessage(err, "intake:feedback.error")),
  });
  const pending = file.isPending;

  const feedback = data?.feedback;
  if (feedback?.mode === "email" && feedback.contact) {
    return <ContactDialog open onOpenChange={setSheetOpen} contact={feedback.contact} />;
  }
  if (feedback?.mode !== "form") return null;

  const send = () => {
    if (!form.rating || pending) return;
    file.mutate({
      ticket: {
        stream: "feedback",
        rating: form.rating,
        likes: form.likes.trim() || null,
        wishes: form.wishes.trim() || null,
        contactable: form.contactable,
        context: form.withContext ? context : null,
      },
      files: form.files,
    });
  };
  const lit = preview || form.rating;

  return (
    <Sheet open onOpenChange={setSheetOpen} modal={!wide}>
      <SheetContent
        side={wide ? null : "bottom"}
        aria-describedby={undefined}
        className={cn(
          "flex flex-col gap-0 p-0",
          wide
            ? "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-4 right-4 bottom-4 max-h-[calc(100dvh-2rem)] w-96 rounded-2xl border"
            : "max-h-[85dvh] rounded-t-2xl"
        )}
        style={wide ? undefined : { paddingBottom: "var(--safe-area-inset-bottom)" }}
        // Docked beside the page, it stays open while the page is used.
        onInteractOutside={wide ? (event) => event.preventDefault() : undefined}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          const chosen = (selector: string) => stars.current?.querySelector<HTMLElement>(selector);
          (chosen('[data-state="checked"]') ?? chosen('[role="radio"]'))?.focus();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            send();
          }
        }}
      >
        {sent ? (
          <div
            role="status"
            className="flex flex-col items-center gap-2 px-6 pt-8 pb-6 text-center"
          >
            <img src={proudSvg} alt="" className="size-20" />
            <SheetTitle ref={thanks} tabIndex={-1} className="text-lg outline-none">
              {t("feedback.thanks")}
            </SheetTitle>
            <span aria-hidden="true">
              <ScaleValue value={sent * 20} display="stars" />
            </span>
            <p className="text-muted-foreground text-sm">{t("feedback.thanksBody")}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => setSheetOpen(false)}
            >
              {t("feedback.done")}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 py-4 pr-12 pl-4">
              <img src={talkingSvg} alt="" className="size-11 shrink-0" />
              <SheetTitle className="text-base leading-snug">{t("feedback.title")}</SheetTitle>
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {/* The kit's radio item draws a dot; a rating is drawn as stars. */}
                <RadioGroupPrimitive.Root
                  ref={stars}
                  aria-label={t("feedback.ratingLabel")}
                  orientation="horizontal"
                  className="flex"
                  value={form.rating ? String(form.rating) : ""}
                  onValueChange={(value) => change({ rating: Number(value) as Rating })}
                  disabled={pending}
                  onPointerLeave={() => setPreview(0)}
                >
                  {STARS.map((star) => (
                    <RadioGroupPrimitive.Item
                      key={star}
                      value={String(star)}
                      aria-label={t("feedback.star", {
                        count: star,
                        label: t(`feedback.ratings.${star}`),
                      })}
                      className="rounded-md p-1 transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                      onPointerEnter={() => setPreview(star)}
                    >
                      <Star
                        aria-hidden
                        className={cn(
                          "size-8",
                          star <= lit ? "fill-current text-warning" : "text-muted-foreground/40"
                        )}
                      />
                    </RadioGroupPrimitive.Item>
                  ))}
                </RadioGroupPrimitive.Root>
                <span
                  aria-hidden="true"
                  className={cn("text-sm", lit ? "font-medium" : "text-muted-foreground")}
                >
                  {lit ? t(`feedback.ratings.${lit}`) : t("feedback.pickStar")}
                </span>
              </div>

              {form.rating ? (
                <>
                  <div className="space-y-1.5">
                    <Label htmlFor="feedback-likes">
                      {t("feedback.likesLabel")}{" "}
                      <span className="font-normal text-muted-foreground text-xs">
                        {t("feedback.optional")}
                      </span>
                    </Label>
                    <Textarea
                      id="feedback-likes"
                      rows={2}
                      maxLength={ANSWER_MAX}
                      value={form.likes}
                      onChange={(event) => change({ likes: event.target.value })}
                      placeholder={t("feedback.likesPlaceholder")}
                      disabled={pending}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="feedback-wishes">
                      {t("feedback.wishesLabel")}{" "}
                      <span className="font-normal text-muted-foreground text-xs">
                        {t("feedback.optional")}
                      </span>
                    </Label>
                    <Textarea
                      ref={wishesBox}
                      id="feedback-wishes"
                      rows={3}
                      maxLength={ANSWER_MAX}
                      value={form.wishes}
                      onChange={(event) => change({ wishes: event.target.value })}
                      placeholder={t("feedback.wishesPlaceholder")}
                      disabled={pending}
                    />
                  </div>
                  <EvidencePicker
                    policy={feedback.evidence}
                    files={form.files}
                    onChange={(files) => change({ files })}
                    disabled={pending}
                    label={t("feedback.addPicture")}
                    pasteFrom={wishesBox}
                  />
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="feedback-contactable"
                      checked={form.contactable}
                      onCheckedChange={(checked) => change({ contactable: checked === true })}
                      disabled={pending}
                    />
                    <Label htmlFor="feedback-contactable" className="font-normal">
                      {t("feedback.contactable")}
                    </Label>
                  </div>
                  {/* Somebody stuck needs an answer, which feedback is not. */}
                  {form.rating <= 2 ? (
                    <HelpLink
                      topic={SupportTopic.other}
                      communityId={communityId}
                      label={t("feedback.stuck")}
                    />
                  ) : null}
                </>
              ) : null}
            </div>

            {form.rating ? (
              <div className="space-y-2 border-t px-4 py-3">
                <div className="flex items-center gap-2 text-muted-foreground text-xs">
                  <Switch
                    checked={form.withContext}
                    onCheckedChange={(withContext) => change({ withContext })}
                    aria-label={t("feedback.context.switch")}
                    disabled={pending}
                  />
                  <span className="min-w-0 flex-1">
                    {form.withContext ? t("feedback.context.on") : t("feedback.context.off")}
                  </span>
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-muted-foreground text-xs"
                    aria-expanded={seeing}
                    onClick={() => setSeeing(!seeing)}
                  >
                    {seeing ? t("feedback.context.hide") : t("feedback.context.show")}
                  </Button>
                </div>
                {seeing ? (
                  <dl
                    className={cn(
                      "grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-md bg-muted p-2 text-xs",
                      !form.withContext && "line-through opacity-50"
                    )}
                  >
                    {CONTEXT_FIELDS.filter((field) => context[field]).map((field) => (
                      <div key={field} className="contents">
                        <dt className="text-muted-foreground">
                          {t(`feedback.context.fields.${field}`)}
                        </dt>
                        <dd className="break-all font-mono">{context[field]}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                <div className="flex items-center justify-end gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={pending}
                    onClick={() => setForm(EMPTY_DRAFT)}
                  >
                    {t("feedback.discard")}
                  </Button>
                  <Button type="button" size="sm" disabled={pending} onClick={send}>
                    {t("feedback.submit")}
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
};
