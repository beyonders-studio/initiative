import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { IntakeSettingsRead, IntakeStream } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import {
  useUpdateIntakeGeneralContact,
  useUpdateIntakeStreamContact,
} from "@/hooks/useIntakeSettings";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/**
 * Who a notice tells somebody to contact: one general address, and one per
 * stream. A stream left blank uses the general address — never another
 * stream's — and with neither set the notice names nobody.
 */
export const ContactsCard = ({
  settings,
  settled,
}: {
  settings: IntakeSettingsRead;
  settled: boolean;
}) => {
  const { t } = useTranslation("intake");
  // A stream nobody files into has nobody to point at an address.
  const streams = settings.bindings
    .filter((binding) => binding.filed !== false)
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
    <SettingsSection title={t("contacts.title")} description={t("contacts.description")}>
      <form className="max-w-md space-y-4" onSubmit={onSubmit}>
        <Field label={t("contacts.generalLabel")}>
          <Input
            type="email"
            value={draft.general}
            placeholder={t("contacts.generalPlaceholder")}
            disabled={!settled || saving}
            onChange={(event) => form.set({ general: event.target.value })}
          />
        </Field>
        {streams.map((stream) => (
          <Field key={stream} label={t(`streams.${stream}.title`)}>
            <Input
              type="email"
              value={draft[stream]}
              placeholder={t("contacts.streamPlaceholder")}
              disabled={!settled || saving}
              onChange={(event) => form.set({ [stream]: event.target.value })}
            />
          </Field>
        ))}
        <Button type="submit" disabled={!settled || saving || !changed}>
          {saving ? t("contacts.saving") : t("contacts.save")}
        </Button>
      </form>
    </SettingsSection>
  );
};
