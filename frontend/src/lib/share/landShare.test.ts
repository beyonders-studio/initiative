import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { landShare, readSharedFile } from "@/lib/share/landShare";

// A one-pixel PNG, as a data URL: the shape iOS may hand a shared picture over in.
const PIXEL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const destination = {
  communityId: 3,
  communityName: "Anvil Club",
  initiativeId: 4,
  initiativeName: "Spring Play",
};

// The files handed to the upload helpers, by name: jsdom's XMLHttpRequest
// sends a file's name as "blob", so the wire cannot say.
const uploaded: string[] = [];
vi.mock("@/lib/attachmentUtils", () => ({
  uploadPastedImage: async (_communityId: number, file: File) => {
    uploaded.push(file.name);
    return `/uploads/3/pasted-${file.name}`;
  },
  uploadAttachment: async (_communityId: number, file: File) => {
    uploaded.push(file.name);
    return {
      filename: file.name,
      url: `/uploads/3/${file.name}`,
      content_type: file.type,
      size: 1,
    };
  },
}));

beforeEach(() => {
  uploaded.length = 0;
});

describe("readSharedFile", () => {
  it("adds the extension a shared PDF arrived without", async () => {
    const file = await readSharedFile({
      uri: "data:application/pdf;base64,JVBERi0=",
      name: "minutes",
      mimeType: "application/pdf",
    });
    expect(file.name).toBe("minutes.pdf");
  });

  it("names a picture shared without an extension by its type", async () => {
    const file = await readSharedFile({ uri: PIXEL, name: "IMG_0001", mimeType: "image/png" });
    expect(file.name).toBe("IMG_0001.png");
    expect(file.type).toBe("image/png");
  });

  it("leaves a name that has an extension alone", async () => {
    const file = await readSharedFile({ uri: PIXEL, name: "cat.png", mimeType: "image/png" });
    expect(file.name).toBe("cat.png");
  });
});

describe("landShare", () => {
  it("makes a task with its pictures in the description, and goes to it", async () => {
    let created: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/tasks/", async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 77 });
      })
    );

    const path = await landShare({
      kind: "task",
      destination: { ...destination, projectId: 5, projectName: "Props" },
      title: "Buy props",
      note: "See https://example.com",
      images: [{ uri: PIXEL, name: "cat.png", mimeType: "image/png" }],
    });

    expect(uploaded).toEqual(["cat.png"]);
    expect(created).toEqual({
      title: "Buy props",
      project_id: 5,
      description: "See https://example.com\n\n![cat](/uploads/3/pasted-cat.png)",
    });
    expect(path).toBe("/c/3/i/4/projects/5/tasks/77");
  });

  it("leaves a task with nothing to say without a description", async () => {
    let created: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/tasks/", async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1 });
      })
    );

    await landShare({
      kind: "task",
      destination: { ...destination, projectId: 5 },
      title: "Just a title",
      note: "",
      images: [],
    });

    expect(created).toEqual({ title: "Just a title", project_id: 5 });
  });

  it("makes a document whose body holds the picture it uploaded", async () => {
    let created: {
      name: string;
      file_type: string;
      content: { root: { children: unknown[] } };
    } | null = null;
    server.use(
      communityHttp.post("/files/", async ({ request }) => {
        created = (await request.json()) as typeof created;
        return HttpResponse.json({ id: 12 });
      })
    );

    const path = await landShare({
      kind: "file",
      destination,
      title: "Moodboard",
      note: "",
      images: [{ uri: PIXEL, name: "cat.png", mimeType: "image/png" }],
    });

    expect(uploaded).toEqual(["cat.png"]);
    expect(created).toMatchObject({ name: "Moodboard", initiative_id: 4, file_type: "lexical" });
    expect(JSON.stringify(created)).toContain('"src":"/uploads/3/cat.png"');
    expect(path).toBe("/c/3/i/4/files/12");
  });

  it("posts to the initiative's board", async () => {
    let created: { name: string; body: unknown } | null = null;
    server.use(
      communityHttp.post("/posts/", async ({ request }) => {
        created = (await request.json()) as typeof created;
        return HttpResponse.json({ id: 9 });
      })
    );

    const path = await landShare({
      kind: "post",
      destination,
      title: "Rehearsal moved",
      note: "Now on Friday",
      images: [],
    });

    expect(created).toMatchObject({ name: "Rehearsal moved", initiative_id: 4 });
    expect(JSON.stringify(created)).toContain('"text":"Now on Friday"');
    expect(path).toBe("/c/3/i/4/posts/9");
  });

  describe("uploading the files themselves", () => {
    const PDF = {
      uri: "data:application/pdf;base64,JVBERi0=",
      name: "minutes.pdf",
      mimeType: "application/pdf",
    };
    const PNG = { uri: PIXEL, name: "cat.png", mimeType: "image/png" };

    const uploadsTo = (respond: (name: string) => Response) => {
      const names: string[] = [];
      server.use(
        communityHttp.post("/files/upload", async ({ request }) => {
          const name = /name="name"\r\n\r\n([^\r]*)/.exec(await request.text())?.[1] ?? "";
          names.push(name);
          return respond(name);
        })
      );
      return names;
    };

    it("uploads one file under its name and goes to it", async () => {
      const names = uploadsTo(() => HttpResponse.json({ id: 31 }));

      const path = await landShare({
        kind: "upload",
        destination,
        uploads: [{ file: PDF, name: "Committee minutes" }],
      });

      expect(names).toEqual(["Committee minutes"]);
      expect(path).toBe("/c/3/i/4/files/31");
    });

    it("goes to the initiative's files after several", async () => {
      let id = 40;
      const names = uploadsTo(() => HttpResponse.json({ id: id++ }));
      const landed: string[] = [];

      const path = await landShare({
        kind: "upload",
        destination,
        uploads: [
          { file: PDF, name: "minutes" },
          { file: PNG, name: "cat" },
        ],
        onUploaded: ({ name }) => landed.push(name),
      });

      expect(names).toEqual(["minutes", "cat"]);
      expect(landed).toEqual(["minutes", "cat"]);
      expect(path).toBe("/c/3/i/4/files");
    });

    it("stops at a name already taken, having said which landed", async () => {
      const names = uploadsTo((name) =>
        name === "taken"
          ? HttpResponse.json({ detail: "FILE_NAME_ALREADY_EXISTS" }, { status: 409 })
          : HttpResponse.json({ id: 1 })
      );
      const landed: string[] = [];

      await expect(
        landShare({
          kind: "upload",
          destination,
          uploads: [
            { file: PDF, name: "fine" },
            { file: PNG, name: "taken" },
            { file: PDF, name: "never tried" },
          ],
          onUploaded: ({ name }) => landed.push(name),
        })
      ).rejects.toThrow();

      expect(names).toEqual(["fine", "taken"]);
      expect(landed).toEqual(["fine"]);
    });
  });
});
