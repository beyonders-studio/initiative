import { ChevronsUpDown, Users, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { cn } from "@/ui/lib/utils";

/** How the app knows a person: Initiative by number, a plug-in by the
 *  reference it is given for them. */
export type MemberId = number | string;

/** Whether `id` is one a person is known by. */
export const isMemberId = (id: unknown): id is MemberId =>
  (typeof id === "number" && Number.isFinite(id)) || (typeof id === "string" && id !== "");

/** Someone a picker or a field may name, as they are drawn, by the id the app
 *  knows them by (`Id`). */
export interface Member<Id extends MemberId = number> {
  id: Id;
  name: string;
  /** Their picture; their initials are drawn where they have none. */
  picture?: string;
  initials: string;
}

/** Whose people are offered: the community's, those who can open one row of
 *  a tool (`T`), or one initiative's members. */
export type MemberScope<T extends string = Tool> =
  | { type: "community" }
  | { type: "canOpen"; tool: T; id: number | null | undefined }
  | { type: "initiative"; initiativeId: number | null | undefined };

/**
 * The members of `scope` whose names match `search`, or those `ids` names. A
 * method, whose parameters TypeScript checks both ways: one that knows its
 * people by number and its tools by name is taken wherever the kit takes any,
 * as the kit asks it only of the people and rows the same app gave it.
 */
export type SearchMembers<Id extends MemberId = number, T extends string = Tool> = {
  search(scope: MemberScope<T>, query: { search: string } | { ids: Id[] }): Promise<Member<Id>[]>;
}["search"];

export type MemberPickerProps<Id extends MemberId = number> = {
  /** Finds the people listed, and who a bare `value` names. */
  searchMembers: SearchMembers<Id, string>;
  scope: MemberScope<string>;
  /** Shown in the trigger while nobody is picked, and in the search field. */
  placeholder: string;
  /** Shown when nobody matches. */
  emptyMessage?: string;
  disabled?: boolean;
  /** Ties the trigger to a `<Label htmlFor>`. */
  id?: string;
  className?: string;
  "aria-label"?: string;
} & (
  | {
      multiple?: false;
      /** The person picked, by id; null for nobody. */
      value: Id | null;
      /** Who `value` names, so the trigger shows them without a lookup. Without
       *  it, the value is looked up. */
      selected?: Member<Id> | null;
      /** The id picked and who it names; null for nobody. */
      onChange: (id: Id | null, member: Member<Id> | null) => void;
    }
  | {
      /** Picks several, each shown as a chip that takes them off again. */
      multiple: true;
      /** The people picked, by id. */
      value: Id[];
      /** Who `value` names, as far as the caller knows; the rest are looked up. */
      selected?: Member<Id>[];
      /** The ids picked and who they name. */
      onChange: (ids: Id[], members: Member<Id>[]) => void;
      /** Choices that name nobody in particular, listed above the people and
       *  each picked on its own. */
      extras?: readonly {
        value: string;
        label: string;
        selected: boolean;
        onToggle: (selected: boolean) => void;
      }[];
      /** The reader, listed first and marked as them. */
      currentUserId?: Id;
      /** "filter" is the compact field of a row of filters: it says who or how
       *  many are picked, with no chips and no Clear. */
      variant?: "default" | "filter";
    }
);

const MemberAvatar = ({ member, className }: { member: Member<MemberId>; className?: string }) => (
  <Avatar className={cn("h-6 w-6 border text-3xs", className)}>
    {member.picture ? <AvatarImage src={member.picture} alt={member.name} /> : null}
    <AvatarFallback userId={member.id}>{member.initials}</AvatarFallback>
  </Avatar>
);

/** One of the people in `scope`, or several with `multiple`, searched for by
 *  name while the list is open. */
export const MemberPicker = <Id extends MemberId = number>(props: MemberPickerProps<Id>) => {
  const {
    searchMembers,
    scope,
    placeholder,
    emptyMessage,
    disabled = false,
    id,
    className,
    "aria-label": ariaLabel,
  } = props;
  const { t } = useTranslation("ui");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Member<Id>[]>([]);
  const [loading, setLoading] = useState(false);
  // Everyone found or looked up so far, so a pick stays named once the search
  // moves on.
  const [named, setNamed] = useState<ReadonlyMap<Id, Member<Id>>>(() => new Map());
  const remember = useCallback(
    (members: Member<Id>[]) =>
      setNamed((known) => new Map([...known, ...members.map((each) => [each.id, each] as const)])),
    []
  );

  // Kept by what it says, so a scope given afresh each render asks nothing new.
  const scopeKey = JSON.stringify(scope);
  const search = useCallback(
    (asked: Parameters<SearchMembers<Id>>[1]) => searchMembers(JSON.parse(scopeKey), asked),
    [searchMembers, scopeKey]
  );

  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoading(true);
    search({ search: query })
      .then((members) => {
        if (!current) return;
        setFound(members);
        remember(members);
      })
      .catch(() => undefined)
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [open, query, search, remember]);

  const ids = props.multiple ? props.value : props.value === null ? [] : [props.value];
  const selected = props.multiple ? (props.selected ?? []) : props.selected ? [props.selected] : [];
  const known = new Map([...named, ...selected.map((each) => [each.id, each] as const)]);
  const draw = (each: Id): Member<Id> =>
    known.get(each) ?? {
      id: each,
      name: t("memberPicker.userWithId", { id: each }),
      initials: "?",
    };

  // Written out, so a value given afresh each render looks nobody up again.
  const unnamed = JSON.stringify(ids.filter((each) => !known.has(each)));
  useEffect(() => {
    const asked: Id[] = JSON.parse(unnamed);
    if (asked.length === 0) return;
    let current = true;
    search({ ids: asked })
      .then((members) => {
        if (current) remember(members);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [unnamed, search, remember]);

  const shared = {
    id,
    className,
    onSearchChange: setQuery,
    onOpenChange: setOpen,
    loading: loading && found.length === 0,
    searchPlaceholder: placeholder,
    emptyMessage,
    disabled,
  };

  if (!props.multiple) {
    const { value, onChange } = props;
    const drawn = value === null ? null : draw(value);
    return (
      <Combobox
        {...shared}
        items={[
          // Clearing is listed first while there is something to clear: "" is
          // no member's id.
          ...(value !== null ? [{ value: "", label: t("clear"), icon: X }] : []),
          ...found.map((member) => ({
            value: String(member.id),
            label: member.name,
            icon: <MemberAvatar member={member} />,
          })),
        ]}
        value={value !== null ? String(value) : null}
        onValueChange={(next) => {
          const member = found.find((each) => String(each.id) === next) ?? null;
          onChange(member ? member.id : null, member);
        }}
        trigger={
          <Button
            variant="outline"
            role="combobox"
            aria-label={ariaLabel}
            disabled={disabled}
            className={cn("w-full justify-between", !drawn && "text-muted-foreground", className)}
          >
            <span className="flex min-w-0 items-center gap-2">
              {drawn ? <MemberAvatar member={drawn} className="h-5 w-5 text-3xs" /> : null}
              <span className="truncate">{drawn ? drawn.name : placeholder}</span>
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        }
      />
    );
  }

  const { value, onChange, extras = [], currentUserId, variant = "default" } = props;
  const pick = (next: Id[]) => onChange(next, next.map(draw));
  const foundIds = new Set(found.map((each) => each.id));
  // The people picked stay listed when the search misses them, so they can be
  // taken off; then the reader goes first.
  const listed = [...value.filter((each) => !foundIds.has(each)).map(draw), ...found].sort(
    (a, b) => Number(b.id === currentUserId) - Number(a.id === currentUserId)
  );
  // Each person listed by the value a row of the list carries.
  const listedIds = new Map(listed.map((member) => [String(member.id), member.id]));

  const picker = (
    <Combobox
      {...shared}
      multiple
      items={[
        ...extras.map((extra) => ({ value: extra.value, label: extra.label })),
        ...listed.map((member) => ({
          value: String(member.id),
          label: member.name,
          icon: <MemberAvatar member={member} />,
          hint: member.id === currentUserId ? t("memberPicker.you") : undefined,
        })),
      ]}
      value={[
        ...extras.filter((extra) => extra.selected).map((extra) => extra.value),
        ...value.map(String),
      ]}
      // One row changes at a time: an extra, or else a person.
      onValueChange={(next) => {
        const extra = extras.find((each) => next.includes(each.value) !== each.selected);
        if (extra) return extra.onToggle(!extra.selected);
        pick(
          next
            .filter((each) => !extras.some((other) => other.value === each))
            .flatMap((each) => listedIds.get(each) ?? [])
        );
      }}
      placeholder={placeholder}
      aria-label={ariaLabel}
      trigger={
        variant === "filter" ? undefined : (
          <Button
            variant="outline"
            role="combobox"
            aria-label={ariaLabel}
            disabled={disabled}
            className={cn(
              "h-auto min-h-10 w-full justify-start",
              value.length === 0 && "text-muted-foreground"
            )}
          >
            <Users className="h-4 w-4 shrink-0 opacity-50" />
            {value.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {value.map((each) => {
                  const member = draw(each);
                  return (
                    <span
                      key={each}
                      className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary py-0.5 pr-1.5 pl-1 font-medium text-secondary-foreground text-xs"
                    >
                      <MemberAvatar member={member} className="h-4 w-4 text-3xs" />
                      <span className="truncate">{member.name}</span>
                      <button
                        type="button"
                        className="rounded-sm hover:opacity-70 focus:outline-none"
                        aria-label={t("memberPicker.remove", { name: member.name })}
                        onClick={(event) => {
                          event.stopPropagation();
                          event.preventDefault();
                          if (!disabled) pick(value.filter((other) => other !== each));
                        }}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  );
                })}
              </div>
            ) : (
              <span>{placeholder}</span>
            )}
          </Button>
        )
      }
    />
  );

  if (variant === "filter") return picker;
  return (
    <div className={cn("space-y-3", className)}>
      {picker}
      {value.length > 0 ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => pick([])}
          disabled={disabled}
        >
          {t("memberPicker.clearAll")}
        </Button>
      ) : null}
    </div>
  );
};
