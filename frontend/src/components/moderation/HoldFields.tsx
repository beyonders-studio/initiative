/**
 * Why something is held for the platform: the reason, the law where it may be
 * illegal, and a note only the platform reads. Shared by every surface that
 * holds something, so each asks it the same way.
 */
import { useTranslation } from "react-i18next";

import {
  HoldReason,
  type HoldReason as HoldReasonValue,
  LegalBasis,
  type LegalBasis as LegalBasisValue,
} from "@/api/generated/initiativeAPI.schemas";
import { Field } from "@/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

/** Matches the column behind it. */
const NOTE_MAX = 2000;

const REASONS: HoldReasonValue[] = [HoldReason.legal_request, HoldReason.illegal_content];

const BASES: LegalBasisValue[] = [
  LegalBasis.child_safety,
  LegalBasis.terrorism,
  LegalBasis.intellectual_property,
  LegalBasis.fraud,
  LegalBasis.privacy,
  LegalBasis.other,
];

export interface HoldWhy {
  reason: HoldReasonValue;
  basis: LegalBasisValue | "";
  note: string;
}

export const emptyHoldWhy = (reason: HoldReasonValue = HoldReason.legal_request): HoldWhy => ({
  reason,
  basis: "",
  note: "",
});

/** Whether ``why`` says enough to hold something. */
export const holdWhyReady = (why: HoldWhy) =>
  why.reason !== HoldReason.illegal_content || why.basis !== "";

/** ``why`` as the API takes it. */
export const holdWhyBody = (why: HoldWhy) => ({
  reason: why.reason,
  legal_basis: why.reason === HoldReason.illegal_content && why.basis ? why.basis : null,
  note: why.note.trim() || null,
});

export const HoldFields = ({
  value,
  onChange,
  idPrefix = "hold",
}: {
  value: HoldWhy;
  onChange: (value: HoldWhy) => void;
  idPrefix?: string;
}) => {
  const { t } = useTranslation("moderation");
  return (
    <div className="space-y-4">
      <Field label={t("hold.reasonLabel")}>
        <Select
          value={value.reason}
          onValueChange={(v) => onChange({ ...value, reason: v as HoldReasonValue })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REASONS.map((reason) => (
              <SelectItem key={reason} value={reason}>
                {t(`hold.reasons.${reason}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {value.reason === HoldReason.illegal_content ? (
        <Field label={t("hold.basisLabel")}>
          <Select
            value={value.basis}
            onValueChange={(v) => onChange({ ...value, basis: v as LegalBasisValue })}
          >
            <SelectTrigger>
              <SelectValue placeholder={t("hold.basisPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {BASES.map((basis) => (
                <SelectItem key={basis} value={basis}>
                  {t(`hold.bases.${basis}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      ) : null}
      <Field label={t("hold.noteLabel")} hint={t("hold.noteHelp")}>
        <Textarea
          value={value.note}
          onChange={(e) => onChange({ ...value, note: e.target.value })}
          placeholder={t("hold.notePlaceholder")}
          rows={3}
          maxLength={NOTE_MAX}
        />
      </Field>
    </div>
  );
};
