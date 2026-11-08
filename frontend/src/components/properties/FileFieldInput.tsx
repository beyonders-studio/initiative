import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Combobox, type ComboboxItem } from "@/ui/combobox";
import { host } from "@/ui/host";

import { FileFieldName } from "./PropertyValueCell";
import type { FileFieldValue } from "./propertyHelpers";

/** A file the picker offers: its id, and its row. */
export type FileChoice = Pick<ComboboxItem, "label" | "icon" | "sublabel"> & { id: number };

/** What a file field asks of the app around it. */
export interface FileFieldFiles {
  /** The files the reader may pick that match `query`; with "", the ones
   *  offered before anything is typed. */
  find: (query: string) => Promise<FileChoice[]>;
  /** The path of a file's page. */
  href: (fileId: number) => string;
  /** The file drawn under its name, read-only, where the app draws it. */
  preview: (file: FileFieldValue) => ReactNode;
  /** A way to make a new file beside the picker, which hands it to `take`. */
  newFile: (take: (file: FileFieldValue) => void) => ReactNode;
}

interface FileFieldInputProps {
  /** The id of the file the field holds. */
  value: number | null;
  /** The field as the server last read it back. */
  shown: FileFieldValue | null;
  onChange: (value: number | null) => void;
  files: FileFieldFiles;
  disabled?: boolean;
}

/**
 * A file field: the one file it holds, a link to it, and a way to pick
 * another or make a new one.
 */
export const FileFieldInput = ({
  value,
  shown,
  onChange,
  files,
  disabled = false,
}: FileFieldInputProps) => {
  const { t } = useTranslation(["relations", "search"]);
  // What was picked here, drawn until the server reads it back: the picker
  // knows only the file's name.
  const [picked, setPicked] = useState<FileFieldValue | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // The last answer, listed until the next one comes.
  const [found, setFound] = useState<FileChoice[] | null>(null);

  const { find } = files;
  useEffect(() => {
    if (!open) return;
    let current = true;
    const answer = (choices: FileChoice[]) => {
      if (current) setFound(choices);
    };
    void find(query).then(answer, () => answer([]));
    return () => {
      current = false;
    };
  }, [find, open, query]);

  const file =
    value === null ? null : ([shown, picked].find((each) => each?.id === value) ?? { id: value });
  const take = (next: FileFieldValue) => {
    setPicked(next);
    onChange(next.id);
  };

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {file ? (
        file.name ? (
          <host.Link
            to={files.href(file.id)}
            className="min-w-0 self-start text-sm hover:underline"
          >
            <FileFieldName file={file} />
          </host.Link>
        ) : (
          <FileFieldName file={file} />
        )
      ) : null}
      {file ? files.preview(file) : null}
      {disabled ? null : (
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <Combobox
              items={(found ?? []).map(({ id, ...row }) => ({
                ...row,
                value: String(id),
                hint: t("search:types.file"),
              }))}
              value={null}
              onValueChange={(next) => {
                const choice = found?.find((each) => String(each.id) === next);
                if (choice) take({ id: choice.id, name: choice.label });
              }}
              onSearchChange={setQuery}
              onOpenChange={setOpen}
              loading={found === null}
              placeholder={t("relations:dialog.entityPlaceholder")}
              searchPlaceholder={t("relations:dialog.entityPlaceholder")}
              emptyMessage={t("relations:dialog.noResults")}
              aria-label={t("relations:dialog.entity")}
            />
          </div>
          {files.newFile(take)}
        </div>
      )}
    </div>
  );
};
