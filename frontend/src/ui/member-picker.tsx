import { ChevronsUpDown, Users, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { cn } from "@/ui/lib/utils";

/** Someone a picker or a field may name, as they are drawn. */
export interface Member {
  id: number;
  name: string;
  /** Their picture; their initials are drawn where they have none. */
  picture?: string;
  initials: string;
}

/** Whose people are offered: the community's, those who can open one row, or
 *  one initiative's members. */
export type MemberScope =
  | { type: "community" }
  | { type: "canOpen"; tool: Tool; id: number | null | undefined }
  | { type: "initiative"; initiativeId: number | null | undefined };

/** The members of `scope` whose names match `search`, or those `ids` names. */
export type SearchMembers = (
  scope: MemberScope,
  query: { search: string } | { ids: number[] }
) => Promise<Member[]>;

export type MemberPickerProps = {
  /** Finds the people listed, and who a bare `value` names. */
  searchMembers: SearchMembers;
  scope: MemberScope;
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
      value: number | null;
      /** Who `value` names, so the trigger shows them without a lookup. Without
       *  it, the value is looked up. */
      selected?: Member | null;
      /** The id picked and who it names; null for nobody. */
      onChange: (id: number | null, member: Member | null) => void;
    }
  | {
      /** Picks several, each shown as a chip that takes them off again. */
      multiple: true;
      /** The people picked, by id. */
      value: number[];
      /** Who `value` names, as far as the caller knows; the rest are looked up. */
      selected?: Member[];
      /** The ids picked and who they name. */
      onChange: (ids: number[], members: Member[]) => void;
      /** Choices that name nobody in particular, listed above the people and
       *  each picked on its own. */
      extras?: readonly {
        value: string;
        label: string;
        selected: boolean;
        onToggle: (selected: boolean) => void;
      }[];
      /** The reader, listed first and marked as them. */
      currentUserId?: number;
      /** "filter" is the compact field of a row of filters: it says who or how
       *  many are picked, with no chips and no Clear. */
      variant?: "default" | "filter";
    }
);

const MemberAvatar = ({ member, className }: { member: Member; className?: string }) => (
  <Avatar className={cn("h-6 w-6 border text-3xs", className)}>
    {member.picture ? <AvatarImage src={member.picture} alt={member.name} /> : null}
    <AvatarFallback userId={member.id}>{member.initials}</AvatarFallback>
  </Avatar>
);

/** One of the people in `scope`, or several with `multiple`, searched for by
 *  name while the list is open. */
export const MemberPicker = (props: MemberPickerProps) => {
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
  const [found, setFound] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  // Everyone found or looked up so far, so a pick stays named once the search
  // moves on.
  const [named, setNamed] = useState<ReadonlyMap<number, Member>>(() => new Map());
  const remember = useCallback(
    (members: Member[]) =>
      setNamed((known) => new Map([...known, ...members.map((each) => [each.id, each] as const)])),
    []
  );

  // Kept by what it says, so a scope given afresh each render asks nothing new.
  const scopeKey = JSON.stringify(scope);
  const search = useCallback(
    (asked: Parameters<SearchMembers>[1]) => searchMembers(JSON.parse(scopeKey), asked),
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
  const draw = (each: number): Member =>
    known.get(each) ?? {
      id: each,
      name: t("memberPicker.userWithId", { id: each }),
      initials: "?",
    };

  // Joined, so a value given afresh each render looks nobody up again.
  const unnamed = ids.filter((each) => !known.has(each)).join(",");
  useEffect(() => {
    if (!unnamed) return;
    let current = true;
    search({ ids: unnamed.split(",").map(Number) })
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
  const pick = (next: number[]) => onChange(next, next.map(draw));
  const foundIds = new Set(found.map((each) => each.id));
  // The people picked stay listed when the search misses them, so they can be
  // taken off; then the reader goes first.
  const listed = [...value.filter((each) => !foundIds.has(each)).map(draw), ...found].sort(
    (a, b) => Number(b.id === currentUserId) - Number(a.id === currentUserId)
  );

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
        pick(next.filter((each) => !extras.some((other) => other.value === each)).map(Number));
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
