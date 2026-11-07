/**
 * The card an app sends the system browser to, to run one passkey prompt.
 *
 * A passkey belongs to the deployment's domain and the browser is what decides
 * which domain it is in, so an app whose own page is elsewhere opens this one.
 * The prompt's options arrive in the fragment; the credential, or the name of
 * how the prompt ended, goes back to the app at `PROMPT_CALLBACK`, and the app
 * finishes the ceremony itself.
 */
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ServerChip } from "@/components/auth/ServerChoice";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PROMPT_CALLBACK, type PromptKind, runPrompt } from "@/lib/passkeys";

/** The prompt the fragment asks for, with the id its answer goes back under,
 *  or null for a link that carries none. */
const askedFor = (hash: string): { kind: PromptKind; options: unknown; prompt: string } | null => {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const prompt = params.get("prompt");
  if (!prompt) return null;
  for (const kind of ["get", "create"] as const) {
    const options = params.get(kind);
    if (options === null) continue;
    try {
      return { kind, options: JSON.parse(options) as unknown, prompt };
    } catch {
      return null;
    }
  }
  return null;
};

export const PasskeyRelayCard = () => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  // Read once: the fragment is the app's, and nothing else on the page sets it.
  const [asked] = useState(() => askedFor(window.location.hash));
  const [busy, setBusy] = useState(false);
  // The link back to the app, once the prompt has ended.
  const [answer, setAnswer] = useState<string | null>(null);

  // Nothing starts on its own here: a prompt wants a press behind it.
  const run = async () => {
    if (!asked) return;
    setBusy(true);
    let ended: Record<string, string>;
    try {
      ended = { credential: JSON.stringify(await runPrompt(asked.kind, asked.options)) };
    } catch (err) {
      ended = { error: err instanceof Error ? err.name : "UnknownError" };
    } finally {
      setBusy(false);
    }
    const back = `${PROMPT_CALLBACK}?${new URLSearchParams({ prompt: asked.prompt, ...ended })}`;
    setAnswer(back);
    window.location.assign(back);
  };

  return (
    <Card className="w-full max-w-md shadow-lg">
      <CardHeader>
        <CardTitle>{t("auth:login.passkeyRelayTitle")}</CardTitle>
        <CardDescription>{t("auth:login.passkeyRelaySubtitle")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!asked ? (
          <p className="text-destructive text-sm">{t("errors:NATIVE_APP_UPDATE_REQUIRED")}</p>
        ) : answer ? (
          <>
            <p className="text-muted-foreground text-sm">{t("auth:login.passkeyReturnToApp")}</p>
            <Button asChild className="w-full" variant="outline">
              <a href={answer}>{t("auth:login.passkeyOpenApp")}</a>
            </Button>
          </>
        ) : (
          <Button className="w-full" type="button" disabled={busy} onClick={() => void run()}>
            <KeyRound className="h-4 w-4" />
            {busy ? t("auth:login.passkeyWorking") : t("auth:login.passkeyContinue")}
          </Button>
        )}
      </CardContent>
      <CardFooter>
        <ServerChip />
      </CardFooter>
    </Card>
  );
};
