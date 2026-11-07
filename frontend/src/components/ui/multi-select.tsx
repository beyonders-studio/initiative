import { Check } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface MultiSelectOption {
  value: string;
  label: string;
  /** Heading to list this option under. Ungrouped options come first, then
   *  each group in the order it first appears. */
  group?: string;
}

interface MultiSelectProps {
  /** Ties the trigger to a `<Label htmlFor>`. A `combobox` takes no accessible
   *  name from its own contents, so without this the control is unnamed. */
  id?: string;
  selectedValues: string[];
  options: MultiSelectOption[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
}

export const MultiSelect = ({
  id,
  selectedValues,
  options,
  onChange,
  placeholder,
  emptyMessage,
  disabled = false,
  className,
}: MultiSelectProps) => {
  const { t } = useTranslation("ui");
  const resolvedPlaceholder = placeholder ?? t("multiSelect.placeholder");
  const resolvedEmptyMessage = emptyMessage ?? t("multiSelect.empty");
  const toggleValue = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((v) => v !== value));
    } else {
      onChange([...selectedValues, value]);
    }
  };

  const selectAll = () => {
    onChange(options.map((option) => option.value));
  };

  const clearAll = () => {
    onChange([]);
  };

  const displayValue = useMemo(() => {
    if (selectedValues.length === 0) {
      return resolvedPlaceholder;
    }
    if (selectedValues.length === options.length) {
      return t("multiSelect.allSelected");
    }
    if (selectedValues.length === 1) {
      const option = options.find((o) => o.value === selectedValues[0]);
      return option?.label ?? resolvedPlaceholder;
    }
    return t("multiSelect.countSelected", { count: selectedValues.length });
  }, [selectedValues, options, resolvedPlaceholder, t]);

  // Ungrouped first, then each group in the order it first appears — the
  // caller's ordering is the one the reader sees.
  const ungrouped = useMemo(() => options.filter((option) => !option.group), [options]);
  const groups = useMemo(() => {
    const byHeading = new Map<string, MultiSelectOption[]>();
    for (const option of options) {
      if (!option.group) continue;
      const existing = byHeading.get(option.group);
      if (existing) existing.push(option);
      else byHeading.set(option.group, [option]);
    }
    return [...byHeading.entries()];
  }, [options]);

  if (options.length === 0) {
    return <p className="text-muted-foreground text-sm">{resolvedEmptyMessage}</p>;
  }

  const renderOption = (option: MultiSelectOption) => {
    const isSelected = selectedValues.includes(option.value);
    return (
      <SelectItem
        key={option.value}
        value={option.value}
        onPointerUp={(e) => {
          e.preventDefault();
          toggleValue(option.value);
        }}
        onPointerDown={(e) => {
          e.preventDefault();
        }}
      >
        <div className="flex w-full items-center gap-2">
          <div className="flex h-4 w-4 items-center justify-center">
            {isSelected ? <Check className="h-4 w-4" /> : null}
          </div>
          <span>{option.label}</span>
        </div>
      </SelectItem>
    );
  };

  return (
    <Select value="__multiselect__" disabled={disabled}>
      <SelectTrigger id={id} className={className}>
        <SelectValue>
          <span className={selectedValues.length === 0 ? "text-muted-foreground" : ""}>
            {displayValue}
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <div
          className="flex flex-col gap-0.5 border-border border-b pb-1"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={selectAll}
            disabled={selectedValues.length === options.length}
            className="h-8 w-full justify-start px-2 font-normal"
          >
            {t("selectAll")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearAll}
            disabled={selectedValues.length === 0}
            className="h-8 w-full justify-start px-2 font-normal"
          >
            {t("multiSelect.clearAll")}
          </Button>
        </div>
        {ungrouped.map(renderOption)}
        {groups.map(([heading, groupOptions]) => (
          <SelectGroup key={heading}>
            <SelectLabel>{heading}</SelectLabel>
            {groupOptions.map(renderOption)}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
};
