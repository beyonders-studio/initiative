import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { ImportJobRead } from "@/api/generated/initiativeAPI.schemas";

import {
  AtlassianChooseStep,
  AtlassianConnectStep,
  AtlassianExportStep,
  AtlassianFetchingStep,
  AtlassianReviewSummary,
  JiraReviewSummary,
} from "./AtlassianImportSteps";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

function job(overrides: Partial<ImportJobRead> = {}): ImportJobRead {
  return {
    id: 77,
    community_id: 1,
    created_by: 1,
    source: "atlassian",
    params: {},
    status: "queued",
    plan: null,
    result: null,
    error: null,
    expires_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

const CONNECTION = {
  credentials: {
    site_url: "https://acme.atlassian.net",
    email: "me@example.com",
    api_token: "secret",
  },
  projects: [
    { id: "1", key: "ACME", name: "Acme Board", issue_count: 12 },
    { id: "2", key: "OPS", name: "Operations", issue_count: null },
  ],
  spaces: [
    { id: "9", key: "DOCS", name: "Team Docs", page_count: 40 },
    { id: "10", key: "HR", name: "People", page_count: 1 },
  ],
};

const TARGETS = [
  { id: 4, name: "Engineering", canCreateProjects: true, canCreateWikis: true },
  { id: 5, name: "Docs only", canCreateProjects: false, canCreateWikis: true },
];

async function fillConnect() {
  await userEvent.type(screen.getByLabelText(/site address/i), "acme.atlassian.net/jira");
  await userEvent.type(screen.getByLabelText(/atlassian email/i), "me@example.com");
  await userEvent.type(screen.getByLabelText(/api token/i), "secret");
  await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));
}

describe("AtlassianConnectStep", () => {
  it("proves the token and hands back both products' lists", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/imports/atlassian/connect", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            site_url: "https://acme.atlassian.net",
            jira: { available: true, projects: CONNECTION.projects },
            confluence: { available: true, spaces: CONNECTION.spaces },
          },
          { status: 201 }
        );
      })
    );
    const onConnected = vi.fn();
    renderWithProviders(<AtlassianConnectStep onConnected={onConnected} />);
    await fillConnect();

    await waitFor(() => expect(onConnected).toHaveBeenCalled());
    expect(sent).toEqual({
      site_url: "acme.atlassian.net/jira",
      email: "me@example.com",
      api_token: "secret",
    });
    const [connection] = onConnected.mock.calls[0];
    // The site as the server normalised it is what the import will call.
    expect(connection.credentials.site_url).toBe("https://acme.atlassian.net");
    expect(connection.projects).toHaveLength(2);
    expect(connection.spaces).toHaveLength(2);
  });

  it("goes on with whichever product the token can see", async () => {
    server.use(
      communityHttp.post("/imports/atlassian/connect", () =>
        HttpResponse.json(
          {
            site_url: "https://acme.atlassian.net",
            jira: { available: false, reason: "IMPORT_SOURCE_AUTH" },
            confluence: { available: true, spaces: CONNECTION.spaces },
          },
          { status: 201 }
        )
      )
    );
    const onConnected = vi.fn();
    renderWithProviders(<AtlassianConnectStep onConnected={onConnected} />);
    await fillConnect();
    await waitFor(() => expect(onConnected).toHaveBeenCalled());
    expect(onConnected.mock.calls[0][0].projects).toEqual([]);
  });

  it("says so when the token can see neither", async () => {
    server.use(
      communityHttp.post("/imports/atlassian/connect", () =>
        HttpResponse.json(
          {
            site_url: "https://acme.atlassian.net",
            jira: { available: false },
            confluence: { available: false },
          },
          { status: 201 }
        )
      )
    );
    const onConnected = vi.fn();
    renderWithProviders(<AtlassianConnectStep onConnected={onConnected} />);
    await fillConnect();
    expect(
      await screen.findByText(/can't see any Jira projects or Confluence spaces/i)
    ).toBeInTheDocument();
    expect(onConnected).not.toHaveBeenCalled();
  });
});

describe("AtlassianChooseStep", () => {
  it("starts one job with the ticked projects and spaces, the initiative and the options", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/imports/atlassian/import", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(job(), { status: 202 });
      })
    );
    const onStarted = vi.fn();
    renderWithProviders(
      <AtlassianChooseStep connection={CONNECTION} initiatives={TARGETS} onStarted={onStarted} />
    );

    // Counted and uncounted lists both read sensibly.
    expect(screen.getByText("12 issues")).toBeInTheDocument();
    expect(screen.getByText(/not counted/i)).toBeInTheDocument();
    expect(screen.getByText("40 pages")).toBeInTheDocument();

    const start = screen.getByRole("button", { name: /start reading/i });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/Operations/));
    await userEvent.click(screen.getByLabelText(/Team Docs/));
    await userEvent.click(screen.getByLabelText(/bring attachments/i));
    // With projects ticked, only the initiative that takes projects is left,
    // so it is the one chosen.
    await userEvent.click(start);

    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(sent).toMatchObject({
      site_url: "https://acme.atlassian.net",
      email: "me@example.com",
      api_token: "secret",
      initiative_id: 4,
      project_keys: ["OPS"],
      space_keys: ["DOCS"],
      include_comments: true,
      include_attachments: false,
    });
  });

  it("offers every initiative that takes wikis when only spaces are ticked", async () => {
    renderWithProviders(
      <AtlassianChooseStep connection={CONNECTION} initiatives={TARGETS} onStarted={vi.fn()} />
    );
    await userEvent.click(screen.getByLabelText(/Team Docs/));
    // A page has comments and attachments of its own.
    expect(screen.getByLabelText(/bring comments/i)).toBeEnabled();
    expect(screen.getByLabelText(/bring attachments/i)).toBeEnabled();
    await userEvent.click(screen.getByRole("combobox"));
    expect(await screen.findByRole("option", { name: "Docs only" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Engineering" })).toBeInTheDocument();
  });
});

describe("AtlassianExportStep", () => {
  it("sends the export in pieces, then hands it over with where it goes", async () => {
    let sent = "";
    server.use(
      communityHttp.post("/imports/atlassian/export", async ({ request }) => {
        sent = await request.text();
        return HttpResponse.json(job(), { status: 202 });
      })
    );
    const onStarted = vi.fn();
    renderWithProviders(<AtlassianExportStep initiatives={TARGETS} onStarted={onStarted} />);

    const start = screen.getByRole("button", { name: /start reading/i });
    expect(start).toBeDisabled();
    await userEvent.upload(
      screen.getByLabelText(/choose the export/i),
      new File(["zip"], "DOCS.zip", { type: "application/zip" })
    );
    expect(screen.getByText("DOCS.zip")).toBeInTheDocument();
    // Both initiatives take wikis; one has to be picked.
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "Docs only" }));
    await userEvent.click(start);

    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    // The upload it arrived as, and where it goes.
    expect(sent).toMatch(/name="initiative_id"\s+5/);
    expect(sent).toMatch(/name="include_attachments"\s+true/);
    expect(sent).toMatch(/name="upload_id"\s+up-\d+/);
  });

  it("says so when the zip is not a space export", async () => {
    server.use(
      communityHttp.post("/imports/atlassian/export", () =>
        HttpResponse.json({ detail: "IMPORT_ZIP_INVALID" }, { status: 400 })
      )
    );
    renderWithProviders(<AtlassianExportStep initiatives={[TARGETS[0]]} onStarted={vi.fn()} />);
    await userEvent.upload(
      screen.getByLabelText(/choose the export/i),
      new File(["zip"], "backup.zip", { type: "application/zip" })
    );
    await userEvent.click(screen.getByRole("button", { name: /start reading/i }));
    expect(await screen.findByText(/isn't a Confluence space's HTML export/i)).toBeInTheDocument();
  });

  it("is offered from the connect step", async () => {
    const onUseExport = vi.fn();
    renderWithProviders(<AtlassianConnectStep onConnected={vi.fn()} onUseExport={onUseExport} />);
    await userEvent.click(screen.getByRole("button", { name: /html export/i }));
    expect(onUseExport).toHaveBeenCalled();
  });
});

describe("AtlassianFetchingStep", () => {
  it("shows the fetch climbing, then hands over the staged job", async () => {
    let polls = 0;
    server.use(
      communityHttp.get("/imports/jobs/:jobId", () => {
        polls += 1;
        return polls < 2
          ? HttpResponse.json(
              job({
                status: "fetching",
                plan: { atlassian: { projects: 1, tasks: 30, spaces: 1, pages: 4 } },
              })
            )
          : HttpResponse.json(
              job({ status: "staged", plan: { atlassian: { projects: 2, tasks: 55 } } })
            );
      })
    );
    const onStaged = vi.fn();
    renderWithProviders(
      <AtlassianFetchingStep jobId={77} onStaged={onStaged} onStopped={() => {}} />
    );

    expect(
      await screen.findByText(/30 tasks from 1 projects and 4 pages from 1 spaces/i)
    ).toBeInTheDocument();
    await waitFor(() => expect(onStaged).toHaveBeenCalled(), { timeout: 4000 });
    expect(onStaged.mock.calls[0][0].status).toBe("staged");
  });

  it("explains a failed fetch in words, and lets somebody start over", async () => {
    server.use(
      communityHttp.get("/imports/jobs/:jobId", () =>
        HttpResponse.json(job({ status: "failed", error: "IMPORT_SOURCE_RATE_LIMITED" }))
      )
    );
    const onStopped = vi.fn();
    renderWithProviders(
      <AtlassianFetchingStep jobId={77} onStaged={vi.fn()} onStopped={onStopped} />
    );

    expect(await screen.findByText(/slow down/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start over/i }));
    expect(onStopped).toHaveBeenCalled();
  });
});

describe("JiraReviewSummary", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says what arrives and, as plainly, what does not", () => {
    renderWithProviders(
      <JiraReviewSummary
        job={
          job({
            status: "staged",
            plan: {
              atlassian: {
                projects: 2,
                tasks: 40,
                links: 7,
                links_outside_selection: 2,
                comments: 12,
                comments_restricted: 1,
                images: 3,
                image_bytes: 2_500_000,
                files: 2,
                file_bytes: 1024,
                other_attachments: 1,
                sprints: 4,
                sprint_calendars: 0,
                sprints_skipped: "IMPORT_TOOL_DISABLED",
                properties: [{ name: "Story points", type: "number", issue_count: 18 }],
                dropped_fields: ["Watchers too"],
                unreadable_projects: ["HR"],
                projects_over_limit: ["OPS"],
              },
            },
          }) as never
        }
        excluded={new Set()}
        onExcludedChange={() => {}}
      />
    );

    expect(screen.getByText(/40 tasks from 2 project/i)).toBeInTheDocument();
    expect(screen.getByText(/7 links between tasks/i)).toBeInTheDocument();
    expect(screen.getByText(/3 images \(2\.4 MB\)/i)).toBeInTheDocument();
    expect(screen.getByText(/2 attached files, each as a file on its task/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1 attached file that isn't an image stays behind/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Story points")).toBeInTheDocument();
    expect(screen.getByText("18 tasks")).toBeInTheDocument();

    expect(screen.getByText(/not coming across/i)).toBeInTheDocument();
    expect(screen.getByText(/can't read: HR/i)).toBeInTheDocument();
    expect(screen.getByText(/reached its size limit: OPS/i)).toBeInTheDocument();
    expect(screen.getByText(/2 links to issues you didn't pick/i)).toBeInTheDocument();
    expect(screen.getByText(/1 comment only some people/i)).toBeInTheDocument();
    expect(screen.getByText(/4 sprints:/i)).toBeInTheDocument();
    expect(screen.getByText(/Watchers too/)).toBeInTheDocument();
  });

  it("lets a property be unticked, and ticked again", async () => {
    const onExcludedChange = vi.fn();
    const staged = job({
      status: "staged",
      plan: {
        atlassian: {
          tasks: 3,
          projects: 1,
          properties: [
            { name: "Story points", type: "number", issue_count: 3 },
            { name: "Team", type: "select", issue_count: 1 },
          ],
        },
      },
    }) as never;

    const { rerender } = renderWithProviders(
      <JiraReviewSummary job={staged} excluded={new Set()} onExcludedChange={onExcludedChange} />
    );
    const storyPoints = screen.getByRole("checkbox", { name: /story points/i });
    expect(storyPoints).toBeChecked();
    await userEvent.click(storyPoints);
    expect([...onExcludedChange.mock.calls[0][0]]).toEqual(["Story points"]);

    rerender(
      <JiraReviewSummary
        job={staged}
        excluded={new Set(["Story points"])}
        onExcludedChange={onExcludedChange}
      />
    );
    const unticked = screen.getByRole("checkbox", { name: /story points/i });
    expect(unticked).not.toBeChecked();
    await userEvent.click(unticked);
    expect([...onExcludedChange.mock.calls[1][0]]).toEqual([]);
  });
});

describe("AtlassianReviewSummary", () => {
  it("shows each product that was read, and the links joined between them", () => {
    renderWithProviders(
      <AtlassianReviewSummary
        job={job({
          status: "staged",
          plan: {
            atlassian: { projects: 1, tasks: 9, spaces: 1, pages: 12, cross_links: 3 },
          },
        })}
        excluded={new Set()}
        onExcludedChange={() => {}}
      />
    );
    expect(screen.getByText(/9 tasks from 1 project/i)).toBeInTheDocument();
    expect(screen.getByText(/12 pages from 1 spaces/i)).toBeInTheDocument();
    expect(screen.getByText(/3 links between issues and pages, joined up/i)).toBeInTheDocument();
  });

  it("says what a space's attachments become, and which stay behind", () => {
    renderWithProviders(
      <AtlassianReviewSummary
        job={job({
          status: "staged",
          plan: {
            atlassian: {
              spaces: 1,
              pages: 2,
              page_comments: 4,
              page_comments_resolved: 2,
              page_images: 2,
              page_files: 1,
              page_attachment_bytes: 2048,
              page_attachments_skipped: 1,
              page_files_blocked: 2,
            },
          },
        })}
        excluded={new Set()}
        onExcludedChange={() => {}}
      />
    );
    expect(screen.getByText(/4 comments on the pages/i)).toBeInTheDocument();
    expect(screen.getByText(/2 resolved inline comments/i)).toBeInTheDocument();
    expect(screen.getByText(/3 attachments \(2(\.0)? KB\)/i)).toBeInTheDocument();
    expect(screen.getByText(/1 attachment that's too large/i)).toBeInTheDocument();
    expect(screen.getByText(/2 files, because this initiative has files/i)).toBeInTheDocument();
  });

  it("leaves out a product nothing was asked of", () => {
    renderWithProviders(
      <AtlassianReviewSummary
        job={job({ status: "staged", plan: { atlassian: { spaces: 1, pages: 2 } } })}
        excluded={new Set()}
        onExcludedChange={() => {}}
      />
    );
    expect(screen.queryByText(/tasks from/i)).not.toBeInTheDocument();
    expect(screen.getByText(/2 pages from 1 spaces/i)).toBeInTheDocument();
  });
});
