import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  IntakeBindingRead,
  IntakeInitiativeOption,
  IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import { useUpsertIntakeBinding } from "@/hooks/useIntakeSettings";
import { Button } from "@/ui/button";
import { Switch } from "@/ui/switch";

import { bindingBody, StreamDialog } from "./StreamDialog";

interface StreamRowProps {
  binding: IntakeBindingRead;
  /** The stream's own contact, as saved; "" when it uses the general one. */
  contact: string;
  /** The operations community is named, so the stream can be routed. */
  routable: boolean;
  initiatives: IntakeInitiativeOption[];
  /** Both reads have settled, so bindings and options describe one community. */
  settled: boolean;
}

/**
 * One kind of case on one line: where it lands, who to contact about it, and
 * whether it is receiving. Everything else is in its dialog, which is also
 * where an unrouted stream is set up.
 */
export const StreamRow = ({ binding, contact, routable, initiatives, settled }: StreamRowProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;
  const title = t(`streams.${stream}.title`);
  const titleId = useId();
  const [editing, setEditing] = useState(false);
  const upsert = useUpsertIntakeBinding();
  const bound = routable && binding.project_id !== null;
  const filed = binding.filed !== false;

  return (
    <li aria-labelledby={titleId} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
      <div className="min-w-0 grow basis-48">
        <p id={titleId} className="font-medium text-sm">
          {title}
        </p>
        <p className="text-muted-foreground text-xs">{t(`streams.${stream}.description`)}</p>
      </div>

      <div className="min-w-0 grow basis-56 text-sm">
        <p className="text-muted-foreground text-xs">{t("rows.landsIn")}</p>
        {/* The page says once, under the picker, why nothing is routed. */}
        {!routable ? (
          <p className="text-muted-foreground">—</p>
        ) : binding.project_id === null ? (
          <p className="text-muted-foreground">{t("stream.notSetUp")}</p>
        ) : binding.project_archived ? (
          // Archived content takes no writes, so this stream receives nothing
          // however its own switch is set.
          <p className="text-destructive">{t("stream.destinationArchived")}</p>
        ) : (
          <p className="break-words">
            {binding.initiative_name} › {binding.project_name}
          </p>
        )}
        {bound && binding.shares_initiative ? (
          <p className="text-destructive text-xs">{t("rows.sharesInitiative")}</p>
        ) : null}
      </div>

      <div className="min-w-0 grow basis-48 text-sm">
        {filed ? (
          <>
            <p className="text-muted-foreground text-xs">{t("rows.contact")}</p>
            <p className={contact ? "break-all" : "text-muted-foreground"}>
              {contact || t("rows.usesGeneral")}
            </p>
          </>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-3">
        {bound ? (
          <Switch
            aria-label={t("rows.receivingLabel", { stream: title })}
            checked={binding.enabled}
            disabled={!settled || upsert.isPending || binding.project_archived}
            onCheckedChange={(checked) =>
              upsert.mutate({ stream, body: bindingBody(binding, { enabled: Boolean(checked) }) })
            }
          />
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!settled}
          aria-label={t(bound || !routable ? "rows.editLabel" : "rows.setUpLabel", {
            stream: title,
          })}
          onClick={() => setEditing(true)}
        >
          {bound || !routable ? t("rows.edit") : t("rows.setUp")}
        </Button>
      </div>

      <StreamDialog
        binding={binding}
        contact={contact}
        routable={routable}
        initiatives={initiatives}
        open={editing}
        onOpenChange={setEditing}
      />
    </li>
  );
};
