import { Capacitor } from "@capacitor/core";

import { createFile, uploadFile } from "@/api/generated/files/files";
import { FileType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { createPost } from "@/api/generated/posts/posts";
import { createTask } from "@/api/generated/tasks/tasks";
import { uploadAttachment, uploadPastedImage } from "@/lib/attachmentUtils";
import { communityPath } from "@/lib/communityUrl";
import { nameWithoutExtension } from "@/lib/fileUtils";
import { uploadInPieces } from "@/lib/resumableUpload";
import type { SharedFile } from "@/lib/share/pendingShare";
import { shareBody, shareMarkdown } from "@/lib/share/shareContent";
import { taskRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";

/**
 * What a share can become: a task, a document written around it, a post, or
 * the shared files themselves, uploaded.
 */
export type ShareKind = "task" | "file" | "upload" | "post";

export interface ShareDestination {
  communityId: number;
  communityName: string;
  initiativeId: number;
  initiativeName: string;
  /** The project a task goes into; nothing else has one. */
  projectId?: number;
  projectName?: string;
}

/** One shared file to upload, under the name somebody gave it. */
export interface ShareUpload {
  file: SharedFile;
  name: string;
}

export type LandShareInput =
  | {
      kind: "task" | "file" | "post";
      destination: ShareDestination;
      title: string;
      note: string;
      /** The pictures that go into the body. */
      images: SharedFile[];
    }
  | {
      kind: "upload";
      destination: ShareDestination;
      uploads: ShareUpload[];
      /** Told of each file as it lands, so a retry after a failure skips it. */
      onUploaded?: (upload: ShareUpload) => void;
    };

const EXTENSIONS: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/heic": "heic",
  "application/pdf": "pdf",
};

/** Where the web view can read a shared file from. */
export const sharedFileSrc = (file: SharedFile): string =>
  file.uri.startsWith("data:") ? file.uri : Capacitor.convertFileSrc(file.uri);

/**
 * A shared file, read to upload. Some apps share a file without an extension
 * on its name, which the upload would otherwise be stored without.
 */
export async function readSharedFile(shared: SharedFile): Promise<File> {
  const response = await fetch(sharedFileSrc(shared));
  if (!response.ok) throw new Error(`Could not read the shared file (${response.status})`);
  const blob = await response.blob();
  const type = shared.mimeType || blob.type;
  const extension = EXTENSIONS[type];
  const base = shared.name || "file";
  const name = extension && !/\.[^.]+$/.test(base) ? `${base}.${extension}` : base;
  return new File([blob], name, { type });
}

/** What an upload is called until somebody names it, as the files tool does. */
export const uploadName = (file: SharedFile): string => nameWithoutExtension(file.name || "file");

/**
 * Upload each file into the files tool, one after another so a name already
 * taken stops the rest rather than racing them. Answers where to go: the file
 * when there was one, the initiative's files when there were several.
 */
async function landUploads(
  { communityId, initiativeId }: ShareDestination,
  uploads: ShareUpload[],
  onUploaded?: (upload: ShareUpload) => void
): Promise<string> {
  let last: number | null = null;
  for (const upload of uploads) {
    const file = await readSharedFile(upload.file);
    const created = await uploadInPieces(
      communityId,
      file,
      file.name,
      { purpose: "file", initiativeId },
      (upload_id) =>
        uploadFile(communityId, { name: upload.name, initiative_id: initiativeId, upload_id })
    );
    last = created.id;
    onUploaded?.(upload);
  }
  return uploads.length === 1 && last !== null
    ? communityPath(communityId, toolDetailRoute(Tool.file, initiativeId, last))
    : communityPath(communityId, toolListRoute(Tool.file, initiativeId));
}

/**
 * Upload the share's files and make the thing it becomes. Answers the path of
 * what was made, to go to.
 */
export async function landShare(input: LandShareInput): Promise<string> {
  const { destination } = input;
  if (input.kind === "upload") {
    return landUploads(destination, input.uploads, input.onUploaded);
  }

  const { kind, title, note, images } = input;
  const { communityId, initiativeId, projectId } = destination;
  const files = await Promise.all(images.map(readSharedFile));

  if (kind === "task") {
    if (!projectId) throw new Error("A task needs a project");
    // A task's description is markdown, which keeps its pictures the way a
    // pasted one is kept.
    const urls = await Promise.all(files.map((file) => uploadPastedImage(communityId, file)));
    const description = shareMarkdown(
      note,
      files.map((file, index) => ({ name: file.name, url: urls[index] }))
    );
    const task = await createTask(communityId, {
      title,
      project_id: projectId,
      ...(description ? { description } : {}),
    });
    return communityPath(communityId, taskRoute(initiativeId, projectId, task.id));
  }

  const uploads = await Promise.all(files.map((file) => uploadAttachment(communityId, file)));
  const body = shareBody(
    note,
    uploads.map((upload, index) => ({
      src: upload.url,
      altText: nameWithoutExtension(files[index].name),
    }))
  );

  if (kind === "file") {
    const file = await createFile(communityId, {
      name: title,
      initiative_id: initiativeId,
      file_type: FileType.lexical,
      content: { ...body },
    });
    return communityPath(communityId, toolDetailRoute(Tool.file, initiativeId, file.id));
  }

  const post = await createPost(communityId, {
    name: title,
    initiative_id: initiativeId,
    body: { ...body },
  });
  return communityPath(communityId, toolDetailRoute(Tool.post, initiativeId, post.id));
}
