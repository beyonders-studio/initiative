import { FilePlus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { CreateFileDialog } from "@/components/files/CreateFileDialog";
import { Button } from "@/ui/button";

type ProjectRelationshipsProps = {
  projectId: number;
  projectName: string;
  initiativeId: number;
  canCreate: boolean;
  canAttach: boolean;
};

/**
 * What a project is connected to.
 *
 * This was a carousel of file cards with a files-only picker, which
 * could attach one kind of thing out of the fourteen a link may name. It is the
 * generic relations surface now, and the shortcut that made a new file
 * already attached to the project is kept — creating the thing you are about to
 * attach is worth a button of its own, which searching for an existing one is
 * not.
 *
 * A project holding only files looks the way it always did: a heading with
 * nothing under it is not drawn, so the other kinds of link appear only once
 * somebody makes one.
 */
export const ProjectRelationships = ({
  projectId,
  projectName,
  initiativeId,
  canCreate,
  canAttach,
}: ProjectRelationshipsProps) => {
  const { t } = useTranslation("projects");
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <>
      <ToolRelationsPanel
        tool={Tool.project}
        entity={{ id: projectId, initiative_id: initiativeId }}
        canEdit={canAttach}
        entityTitle={projectName}
        headerActions={
          canCreate ? (
            <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
              <FilePlus className="h-4 w-4" />
              {t("files.newFile")}
            </Button>
          ) : null
        }
      />
      <CreateFileDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initiativeId={initiativeId}
        projectId={projectId}
      />
    </>
  );
};
