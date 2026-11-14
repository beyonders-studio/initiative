import { useSearch } from "@tanstack/react-router";
import {
  CircleCheck,
  CircleX,
  Clock,
  Hourglass,
  Link2Off,
  LogIn,
  TriangleAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/icons/LogoIcon";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

/**
 * How a vendor flow ended, in the seven ways it can.
 *
 * Initiative runs the flow and hands the person back here with one word, and
 * the sentence is written here — once, in every language this product speaks.
 *
 * They are told apart by whose move is next, because that is the only thing the
 * reader needs from this page. `awaiting_approval` is the one where the answer
 * is *somebody else's*: a vendor whose organization-wide install belongs to an
 * owner turns a request from anybody else into an approval for one of them, so
 * nothing failed and there is nothing to retry yet. `sign_in_required` is
 * the other: the flow is finished only in the browser where the person who
 * started it is signed in. `taken` is a vendor organization already connected
 * to another community on this server, which the page does not name.
 */
const OUTCOMES = {
  connected: { icon: CircleCheck, tone: "text-emerald-600 dark:text-emerald-400" },
  refused: { icon: CircleX, tone: "text-destructive" },
  expired: { icon: Clock, tone: "text-muted-foreground" },
  not_recorded: { icon: TriangleAlert, tone: "text-amber-600 dark:text-amber-400" },
  awaiting_approval: { icon: Hourglass, tone: "text-sky-600 dark:text-sky-400" },
  sign_in_required: { icon: LogIn, tone: "text-amber-600 dark:text-amber-400" },
  taken: { icon: Link2Off, tone: "text-amber-600 dark:text-amber-400" },
} as const;

type Outcome = keyof typeof OUTCOMES;

function isOutcome(value: unknown): value is Outcome {
  return typeof value === "string" && value in OUTCOMES;
}

/**
 * Where a member lands after a plug-in's vendor flow.
 *
 * Deliberately terminal, and deliberately outside the authenticated tree. The
 * connect opens in its own tab, so this is the last thing in that tab and the
 * only useful action is closing it — the member's real session is still sitting
 * where they left it. Requiring a session to read one word back would mean a
 * login screen at the end of a flow that already succeeded.
 */
export function ConnectedPage() {
  const { t } = useTranslation(["plugins"]);
  const search = useSearch({ strict: false }) as { outcome?: string };

  // Anything else is a link that was edited or truncated. `expired` is the
  // right thing to say about it: start again from the plug-in's settings, which is
  // the remedy for every unreadable ending.
  const outcome: Outcome = isOutcome(search.outcome) ? search.outcome : "expired";
  const { icon: Icon, tone } = OUTCOMES[outcome];

  return (
    <div className="flex min-h-app items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <LogoIcon className="mb-2 h-8 w-8" />
          <Icon className={`h-8 w-8 ${tone}`} aria-hidden />
          <CardTitle>{t(`plugins:connected.${outcome}.title`)}</CardTitle>
          <CardDescription>{t(`plugins:connected.${outcome}.body`)}</CardDescription>
        </CardHeader>
        <CardContent className="text-center text-muted-foreground text-sm">
          {t("plugins:connected.closeTab")}
        </CardContent>
      </Card>
    </div>
  );
}
