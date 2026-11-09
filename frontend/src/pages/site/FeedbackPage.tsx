/**
 * Feedback from any server, on Initiative Cloud: the sheet's form as a page.
 *
 * Other servers open it with the device and page it was sent from in the
 * link's fragment, and a suggestion's page with that suggestion as `?idea=`
 * to add the words to; each is read here once and taken out of the address.
 * Anybody may
 * write; sending takes an account on Cloud, so somebody signed out is sent to
 * sign in, and what they wrote waits for them in this browser. Pictures are
 * added once signed in.
 *
 * Only Cloud serves it: anywhere else the address leads home.
 */

import { Navigate, useLocation, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type DeviceContext,
  FeedbackTopic,
  TicketMode,
} from "@/api/generated/initiativeAPI.schemas";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { CONTEXT_FIELDS } from "@/components/tickets/DeviceContext";
import {
  EMPTY_DRAFT,
  type FeedbackDraft,
  FeedbackForm,
  feedbackTicket,
} from "@/components/tickets/FeedbackForm";
import { useAuth } from "@/hooks/useAuth";
import { useIdea } from "@/hooks/useIdeas";
import { useServer } from "@/hooks/useServer";
import { useFileTicket, useTicketAvailability } from "@/hooks/useTickets";
import { isCloudOrigin } from "@/lib/cloud";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { Card } from "@/ui/card";

/** What a signed-out writer wrote, kept while they sign in. */
const KEPT_KEY = "initiative-feedback-draft";

interface Kept {
  draft: Omit<FeedbackDraft, "files">;
  context: DeviceContext | null;
}

const readKept = (): Kept | null => {
  const raw = getItem(KEPT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Kept;
  } catch {
    return null;
  }
};

/** The device and page it was sent from, as the link's fragment carries them. */
export const contextFromFragment = (hash: string): DeviceContext | null => {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const fields = CONTEXT_FIELDS.flatMap((field) => {
    const value = params.get(field);
    return value ? [[field, value] as const] : [];
  });
  return fields.length ? Object.fromEntries(fields) : null;
};

/** The suggestion `?idea=` names, where it names one. */
const ideaFromSearch = (value: unknown): number | null => {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
};

export const FeedbackPage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const { getServerOrigin } = useServer();
  const navigate = useNavigate();
  const hash = useLocation({ select: (location) => location.hash });
  const ideaParam = (useSearch({ strict: false }) as { idea?: unknown }).idea;
  const [kept] = useState(readKept);
  const [context] = useState(() => kept?.context ?? contextFromFragment(hash));
  const [form, setForm] = useState<FeedbackDraft>(() =>
    kept ? { ...EMPTY_DRAFT, ...kept.draft } : EMPTY_DRAFT
  );
  // The suggestion the page was opened to add to goes on the draft once it
  // is read, as one voted for while writing would.
  const [asked, setAsked] = useState(() => ideaFromSearch(ideaParam));
  const { data: askedIdea } = useIdea(asked ?? Number.NaN);
  if (asked !== null && askedIdea) {
    setAsked(null);
    setForm((current) => ({
      ...current,
      kind: FeedbackTopic.idea,
      idea: { task_id: askedIdea.task_id, title: askedIdea.title },
    }));
  }
  const [sent, setSent] = useState(false);
  const thanks = useRef<HTMLHeadingElement>(null);
  const { data } = useTicketAvailability(null, { enabled: Boolean(user) });

  useEffect(() => {
    // Read once: the draft is the page's now, and the address keeps no copy
    // of where it was sent from.
    if (kept) void removeItem(KEPT_KEY);
    if (hash || ideaParam !== undefined) void navigate({ to: "/feedback", replace: true });
  }, [kept, hash, ideaParam, navigate]);
  useEffect(() => {
    if (sent) thanks.current?.focus();
  }, [sent]);

  const file = useFileTicket(
    {
      onSuccess: () => {
        setSent(true);
        setForm(EMPTY_DRAFT);
      },
    },
    "intake:feedback.error"
  );

  if (!isCloudOrigin(getServerOrigin())) return <Navigate to="/" replace />;

  // Signed in, the server says whether it takes feedback now; where it
  // doesn't, the page is its address or nothing, as the sheet is.
  const feedback = data?.feedback;
  if (user && feedback && feedback.mode !== TicketMode.form) {
    return feedback.mode === TicketMode.email && feedback.contact ? (
      <ContactDialog
        open
        onOpenChange={() => void navigate({ to: "/" })}
        contact={feedback.contact}
      />
    ) : (
      <Navigate to="/" replace />
    );
  }
  // Signing in leaves the page: the words are kept for when it comes back.
  const signIn = () => {
    const { files: _, ...words } = form;
    void setItem(KEPT_KEY, JSON.stringify({ draft: words, context } satisfies Kept));
    void navigate({ to: "/login", search: { next: "/feedback" } });
  };
  const send = () => {
    if (!user) {
      signIn();
      return;
    }
    file.mutate({ ticket: feedbackTicket(form, context), files: form.files });
  };

  return (
    <SignInFrame fillPhone>
      <Card className="flex w-full max-w-md flex-col overflow-hidden max-sm:min-h-app max-sm:rounded-none max-sm:border-0">
        <FeedbackForm
          Title="h1"
          draft={form}
          onChange={(next) => setForm((current) => ({ ...current, ...next }))}
          onDiscard={() => setForm(EMPTY_DRAFT)}
          context={context}
          evidence={feedback?.evidence}
          pending={file.isPending}
          sent={sent}
          submitLabel={user ? t("feedback.submit") : t("feedback.signInToSend")}
          onSend={send}
          onSignIn={signIn}
          onDone={() => void navigate({ to: "/" })}
          thanks={thanks}
        />
      </Card>
    </SignInFrame>
  );
};
