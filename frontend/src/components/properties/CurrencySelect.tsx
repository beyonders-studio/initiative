import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { CurrencyCode } from "@/api/generated/initiativeAPI.schemas";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { collator, displayNames } from "@/lib/intl";

/** The currency a new money property starts in: the one the reader's language
 *  is most often written about. */
export const useDefaultCurrency = (): CurrencyCode => {
  const { t } = useTranslation("properties");
  const code = t("currency.default");
  return code in CurrencyCode ? (code as CurrencyCode) : CurrencyCode.USD;
};

/**
 * The currency a money property's amounts are in, picked by its name in the
 * reader's language or by its code.
 */
export const CurrencySelect = ({
  value,
  onChange,
  disabled = false,
}: {
  value: CurrencyCode;
  onChange: (code: CurrencyCode) => void;
  disabled?: boolean;
}) => {
  const { t, i18n } = useTranslation("properties");
  const items = useMemo(() => {
    const names = displayNames(i18n.language, { type: "currency" });
    const order = collator(i18n.language);
    return Object.values(CurrencyCode)
      .map((code) => ({ value: code, label: `${names.of(code) ?? code} (${code})` }))
      .sort((a, b) => order.compare(a.label, b.label));
  }, [i18n.language]);
  return (
    <SearchableCombobox
      items={items}
      value={value}
      onValueChange={(code) => onChange(code as CurrencyCode)}
      emptyMessage={t("currency.none")}
      disabled={disabled}
      aria-label={t("currency.label")}
    />
  );
};
