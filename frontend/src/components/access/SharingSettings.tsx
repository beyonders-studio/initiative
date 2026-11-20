/**
 * Who else can reach one thing, for someone who may change it: a note said to
 * whoever the next change lets in, and the sharing control. A tool's Access
 * settings and a tool plug-in's row show it alike.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  OwnerPluginSummary,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import type { GrantsChange } from "@/hooks/toolHooks";
import { toast } from "@/lib/mascotToast";
import { Field } from "@/ui/field";
import { Textarea } from "@/ui/textarea";

import { ShareControl } from "./ShareControl";

/** Mirrors the backend's limit on the note, which is the authority. */
const NOTE_MAX_LENGTH = 1000;

export const SharingSettings = ({
  initiativeId,
  grants,
  ownerPlugin,
  canShare,
  setGrants,
}: {
  initiativeId: number | null;
  grants: ResourceGrantSchema[];
  ownerPlugin?: OwnerPluginSummary | null;
  /** Whether the reader may change it; otherwise it is shown as it is. */
  canShare: boolean;
  setGrants: {
    mutate: (change: GrantsChange, options?: { onSuccess?: () => void }) => void;
    isPending: boolean;
  };
}) => {
  const { t } = useTranslation(["common", "access"]);
  // Said to whoever the next change lets in, then cleared.
  const [note, setNote] = useState("");
  const ownerId = grants.find((grant) => grant.level === "owner")?.user_id ?? null;
  return (
    <>
      {canShare ? (
        <Field label={t("access:share.noteLabel")} className="mb-4">
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("access:share.notePlaceholder")}
            maxLength={NOTE_MAX_LENGTH}
            rows={2}
            disabled={setGrants.isPending}
          />
        </Field>
      ) : null}
      <ShareControl
        initiativeId={initiativeId}
        grants={grants}
        ownerId={ownerId}
        ownerPlugin={ownerPlugin ?? null}
        onChange={(next) =>
          setGrants.mutate(
            { grants: next, note: note.trim() || null },
            {
              onSuccess: () => {
                setNote("");
                toast.success(t("common:toolSettings.permissionsUpdated"));
              },
            }
          )
        }
        disabled={!canShare || setGrants.isPending}
      />
    </>
  );
};
