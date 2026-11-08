/**
 * The controls that fill a plug-in endpoint's parameters: a dashboard widget's
 * binding and an action's question share them, so a parameter is asked the
 * same way wherever it is asked.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PluginDataParam } from "@/api/pluginData";
import { usePluginParamOptions } from "@/hooks/usePluginData";
import { asControlValue, asDeclaredList, asDeclaredType } from "@/lib/widgets/pluginParams";
import { localized } from "@/lib/widgets/widgetMeta";
import { Combobox } from "@/ui/combobox";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/**
 * One value, typed, in the type its plug-in declared.
 *
 * The text is held locally for the same reason the list field holds it: what is
 * stored is a *parsed* value, and deriving the text back from it fights whoever
 * is typing. On an `int` parameter every half-finished number — "-", "1." — is
 * not yet an integer, so the stored value is briefly absent, and a field
 * rendering that would blank itself under the cursor.
 */
function PluginParamScalarInput({
  id,
  param,
  value,
  onChange,
}: {
  id: string;
  param: PluginDataParam;
  value: string;
  onChange: (next: string | number | boolean | undefined) => void;
}) {
  const [text, setText] = useState(value);

  // Follow the binding when something else changes it, but never overwrite what
  // is being typed with a re-rendering of what it parsed to.
  useEffect(() => {
    setText((current) =>
      asControlValue(asDeclaredType(param, current)) === value ? current : value
    );
  }, [value, param]);

  return (
    <Input
      id={id}
      type={param.type === "int" || param.type === "number" ? "number" : "text"}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        onChange(asDeclaredType(param, event.target.value));
      }}
    />
  );
}

/**
 * Several values, typed, where the plug-in could not offer a menu for them.
 *
 * The comma lives here and only here. What goes onto the binding is an array —
 * that is the whole point of a parameter declaring `list` — but a person typing
 * a handful of values wants one field, and separating them by commas is what
 * they will do whether or not anything asked them to.
 *
 * The text is held locally rather than derived from the array on every
 * keystroke, because parsing and re-joining as you type eats the separator the
 * moment it is typed: "red," becomes ["red"] becomes "red", and the comma has
 * to be typed again.
 */
function PluginParamListInput({
  id,
  param,
  values,
  onChange,
}: {
  id: string;
  param: PluginDataParam;
  values: string[];
  onChange: (next: (string | number | boolean)[]) => void;
}) {
  const { t } = useTranslation("dashboards");
  const [text, setText] = useState(values.join(", "));

  // Follow the binding when something else changes it — a sibling being
  // re-chosen clears this one, and the field has to show that.
  useEffect(() => {
    setText((current) =>
      current
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean)
        .join(", ") === values.join(", ")
        ? current
        : values.join(", ")
    );
  }, [values]);

  return (
    <>
      <Input
        id={id}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          // Each entry in the type the plug-in declared: `list` says how many, it
          // never says what kind, and the proxy checks every one of them.
          onChange(
            asDeclaredList(
              param,
              event.target.value
                .split(",")
                .map((entry) => entry.trim())
                .filter(Boolean)
            )
          );
        }}
      />
      <p className="text-muted-foreground text-xs">{t("config.pluginParamListHint")}</p>
    </>
  );
}

/**
 * One parameter of a plug-in's read endpoint.
 *
 * This is the control that was missing, and the reason every plug-in parameter was
 * a text box: a manifest can say `options_from` — "the permitted values are
 * what this other read of mine answers" — and nothing on this side read it. A
 * repository, a label, a board are each a fact about one install, known only to
 * the plug-in holding that install's credential, so they cannot be written into a
 * published manifest and there is no list here to fall back on.
 *
 * **A menu that will not resolve leaves the field typeable.** That is the rule,
 * and it is deliberate in both directions. A source can fail to answer for
 * reasons that have nothing to do with the value being wrong — the plug-in is down,
 * nobody has connected a credential yet, a sibling has not been chosen — and a
 * control disabled on any of those grounds has made a configuration that would
 * have worked unreachable until somebody else fixes something. So the fallback
 * is an input, never a dead select.
 */
export function PluginParamControl({
  param,
  pluginId,
  endpointId,
  values,
  open,
  onChange,
}: {
  param: PluginDataParam;
  pluginId: number | undefined;
  endpointId: string | undefined;
  values: Record<string, unknown>;
  open: boolean;
  onChange: (key: string, value: unknown) => void;
}) {
  const { t, i18n } = useTranslation(["dashboards", "common"]);

  // Only the parameters that named a source ask for one, and only while the
  // dialog is open. A sibling's answer is part of the question, so changing it
  // re-asks rather than reusing a menu built for a different one.
  const menu = usePluginParamOptions({
    pluginId,
    endpointId,
    param: param.key,
    params: values,
    enabled: open && Boolean(param.options_from),
  });

  const label = localized(param.label, i18n.language) ?? param.key;
  const value = values[param.key];
  const shown = asControlValue(value);
  const controlId = `plugin-param-${param.key}`;
  const chosen = Array.isArray(value) ? value.map(String) : [];

  const offered = param.options_from
    ? (menu.data?.options ?? [])
    : (param.options ?? []).map((option) => ({ value: option, label: option }));

  const heading = (
    <Label htmlFor={controlId}>
      {label}
      {param.required ? <span className="text-destructive"> *</span> : null}
    </Label>
  );

  // Several values rather than one. `list` is the only thing that says so, and
  // an array is what travels — the alternative it exists to replace is a plug-in
  // declaring a string and documenting a comma, which nothing here could
  // validate or complete.
  if (param.list) {
    return (
      <div className="space-y-2">
        {heading}
        {offered.length ? (
          <Combobox
            multiple
            id={controlId}
            value={chosen}
            items={offered.map((option) => ({
              value: option.value,
              label: option.label ?? option.value,
            }))}
            onValueChange={(next) => onChange(param.key, asDeclaredList(param, next))}
            placeholder={t("dashboards:config.pluginParamPlaceholder")}
          />
        ) : (
          <PluginParamListInput
            id={controlId}
            param={param}
            values={chosen}
            onChange={(next) => onChange(param.key, next)}
          />
        )}
      </div>
    );
  }

  if (offered.length) {
    return (
      <div className="space-y-2">
        {heading}
        <Select
          value={shown}
          onValueChange={(next) => onChange(param.key, asDeclaredType(param, next))}
        >
          <SelectTrigger id={controlId}>
            <SelectValue placeholder={t("dashboards:config.pluginParamPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {offered.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label ?? option.value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  // No menu: either the parameter never named a source, or the source would not
  // resolve. Both end in a field somebody can type into.
  return (
    <div className="space-y-2">
      {heading}
      <PluginParamScalarInput
        id={controlId}
        param={param}
        value={shown}
        onChange={(next) => onChange(param.key, next)}
      />
      {param.options_from && menu.data?.unavailable === "needs-sibling" && (
        <p className="text-muted-foreground text-xs">
          {t("dashboards:config.pluginParamNeedsSibling")}
        </p>
      )}
    </div>
  );
}
