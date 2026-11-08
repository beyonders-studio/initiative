import { INSERT_TABLE_COMMAND } from "@lexical/table";
import type { LexicalEditor } from "lexical";
import { type JSX, useEffect, useState } from "react";

import { Button } from "@/ui/button";
import { DialogFooter } from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

export function InsertTableDialog({
  activeEditor,
  onClose,
}: {
  activeEditor: LexicalEditor;
  onClose: () => void;
}): JSX.Element {
  const [rows, setRows] = useState("5");
  const [columns, setColumns] = useState("5");
  const [isDisabled, setIsDisabled] = useState(true);

  useEffect(() => {
    const row = Number(rows);
    const column = Number(columns);
    if (row && row > 0 && row <= 500 && column && column > 0 && column <= 50) {
      setIsDisabled(false);
    } else {
      setIsDisabled(true);
    }
  }, [rows, columns]);

  const onClick = () => {
    activeEditor.dispatchCommand(INSERT_TABLE_COMMAND, {
      columns,
      rows,
    });

    onClose();
  };

  return (
    <>
      <div className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="rows">Number of rows</Label>
          <Input
            id="rows"
            placeholder={"# of rows (1-500)"}
            onChange={(e) => setRows(e.target.value)}
            value={rows}
            data-test-id="table-modal-rows"
            type="number"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="columns">Number of columns</Label>
          <Input
            id="columns"
            placeholder={"# of columns (1-50)"}
            onChange={(e) => setColumns(e.target.value)}
            value={columns}
            data-test-id="table-modal-columns"
            type="number"
          />
        </div>
      </div>
      <DialogFooter data-test-id="table-model-confirm-insert">
        <Button disabled={isDisabled} onClick={onClick}>
          Confirm
        </Button>
      </DialogFooter>
    </>
  );
}
