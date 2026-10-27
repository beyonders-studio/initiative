import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { endOfMonth, startOfDay, startOfMonth } from "date-fns";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultTaskStatuses } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { dateRangeParams } from "@/components/ui/date-range-field";
import { EMPTY_TASK_FILTERS, taskSpecConditions } from "@/lib/filters/taskFilters";

import { ExportWizard } from "./ExportWizard";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const ESTIMATE = {
  tools: {
    project: { count: 3, disabled: false },
    file: { count: 5, disabled: false },
    queue: { count: 0, disabled: true },
    counter_group: { count: 2, disabled: false },
    calendar: { count: 4, disabled: false },
  },
  uploads_count: 1,
  uploads_bytes: 2_500_000,
  uploads_approximate: true,
  estimated_rows: 40,
  max_rows: 50_000,
  max_upload_bytes: 268_435_456,
};

function stubEstimate(estimate = ESTIMATE) {
  server.use(communityHttp.get("/exports/estimate", () => HttpResponse.json(estimate)));
}

function stubJobLifecycle(capture: (url: URL) => void) {
  server.use(
    communityHttp.get("/exports/community", ({ request }) => {
      capture(new URL(request.url));
      return HttpResponse.json({ id: 77, status: "queued" }, { status: 202 });
    }),
    communityHttp.get("/exports/initiative", ({ request }) => {
      capture(new URL(request.url));
      return HttpResponse.json({ id: 77, status: "queued" }, { status: 202 });
    }),
    communityHttp.get("/exports/jobs/:jobId", ({ params }) => {
      // Fall through for the literal sibling routes (/exports/estimate,
      // /exports/community, /exports/initiative) — only numeric ids are jobs.
      if (Number.isNaN(Number(params.jobId))) {
        return undefined;
      }
      return HttpResponse.json({
        id: 77,
        community_id: 1,
        created_by: 1,
        source: "community",
        template_id: "data-table",
        format: "zip",
        params: {},
        status: "done",
        error: null,
        expires_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }),
    communityHttp.get("/exports/jobs/:jobId/download", () =>
      HttpResponse.text("PK-zip", {
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="community-backup.zip"',
        },
      })
    )
  );
}

describe("ExportWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("walks the backup flow and submits the backup selector", async () => {
    stubEstimate();
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });

    renderWithProviders(
      <ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />
    );

    await userEvent.click(screen.getByRole("button", { name: /importable backup/i }));

    // Estimate renders per-tool counts; a disabled tool shows "Not enabled"
    // with its switch off and locked.
    await screen.findByText("3 items");
    expect(screen.getByText(/not enabled/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /queues/i })).toBeDisabled();
    // Uploads footprint from the estimate, human-formatted.
    expect(screen.getByText(/2\.4 MB/)).toBeInTheDocument();

    // Exclude counters, keep uploads on.
    await userEvent.click(screen.getByRole("switch", { name: /counters/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    // The confirm summary matches the payload: the deselected tool AND the
    // disabled tool (Queues) are absent from the "will export" list.
    const summary = screen.getByText(/files ·/i, { selector: "p" });
    expect(summary.textContent).not.toMatch(/queues/i);
    expect(summary.textContent).not.toMatch(/counters/i);
    expect(summary.textContent).toMatch(/projects/i);

    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    const params = sent!.searchParams;
    expect(params.get("mode")).toBe("backup");
    expect(params.get("include_uploads")).toBe("true");
    expect(JSON.parse(params.get("include")!)).toMatchObject({
      project: true,
      file: true,
      counter_group: false,
      // Disabled tools submit as excluded — matching their locked-off switch.
      queue: false,
    });
    expect(params.get("formats")).toBeNull();

    // The 202 job polls to done and auto-downloads.
    await waitFor(() => expect(downloadBlob).toHaveBeenCalled(), { timeout: 4000 });
    expect(await screen.findByText(/export ready/i)).toBeInTheDocument();
  });

  it("submits per-tool report formats including the file per-type map", async () => {
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });

    renderWithProviders(
      <ExportWizard scope={{ kind: "initiative", initiativeId: 5 }} open onOpenChange={() => {}} />
    );

    await userEvent.click(screen.getByRole("button", { name: /report à la carte/i }));

    // Change the project format from its default (pdf) to CSV. Several tools
    // offer CSV — target the project group's radio by its id.
    const projectCsv = screen
      .getAllByRole("radio", { name: /csv/i })
      .find((radio) => radio.id === "project-csv");
    expect(projectCsv).toBeDefined();
    await userEvent.click(projectCsv!);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    const params = sent!.searchParams;
    expect(params.get("initiative_id")).toBe("5");
    expect(params.get("mode")).toBe("report");
    const formats = JSON.parse(params.get("formats")!);
    expect(formats.project).toBe("csv");
    expect(formats.file).toEqual({ lexical: "pdf", sheet: "xlsx" });
    expect(formats.calendar).toBe("ics");
    expect(params.get("include_uploads")).toBeNull();
  });

  it("resumes the running job's progress view on re-open instead of offering a new flow", async () => {
    stubEstimate();
    server.use(
      communityHttp.get("/exports/community", () =>
        HttpResponse.json({ id: 88, status: "queued" }, { status: 202 })
      ),
      // The job never finishes during this test — it stays queued.
      communityHttp.get("/exports/jobs/:jobId", ({ params }) => {
        if (Number.isNaN(Number(params.jobId))) {
          return undefined;
        }
        return HttpResponse.json({
          id: 88,
          community_id: 1,
          created_by: 1,
          source: "community",
          template_id: "data-table",
          format: "zip",
          params: {},
          status: "queued",
          error: null,
          expires_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      })
    );

    const { rerender } = renderWithProviders(
      <ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />
    );
    await userEvent.click(screen.getByRole("button", { name: /importable backup/i }));
    await screen.findByText("3 items");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));
    await screen.findByText(/preparing your export/i);

    // Close while the job still renders, then re-open: the wizard must land
    // on the progress view for the running job, not the mode step — a second
    // walk-through couldn't start a new job and would silently track this one.
    rerender(<ExportWizard scope={{ kind: "community" }} open={false} onOpenChange={() => {}} />);
    rerender(<ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />);

    expect(await screen.findByText(/preparing your export/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /importable backup/i })).not.toBeInTheDocument();
  });

  it("blocks advancing when every tool is deselected", async () => {
    stubJobLifecycle(() => {});

    renderWithProviders(
      <ExportWizard scope={{ kind: "initiative", initiativeId: 5 }} open onOpenChange={() => {}} />
    );
    await userEvent.click(screen.getByRole("button", { name: /report à la carte/i }));

    for (const switchEl of screen.getAllByRole("switch")) {
      if (switchEl.getAttribute("aria-checked") === "true") {
        await userEvent.click(switchEl);
      }
    }
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

    // Re-including one tool unblocks the step.
    await userEvent.click(screen.getAllByRole("switch")[0]);
    expect(screen.getByRole("button", { name: /next/i })).not.toBeDisabled();
  });

  it("blocks the backup step when the estimate exceeds a ceiling", async () => {
    stubEstimate({
      ...ESTIMATE,
      uploads_bytes: 300_000_000,
      max_upload_bytes: 268_435_456,
    });

    renderWithProviders(
      <ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />
    );
    await userEvent.click(screen.getByRole("button", { name: /importable backup/i }));

    expect(await screen.findByText(/exceed the 256 MB limit/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

    // Excluding uploads clears the block (the re-fetched estimate reflects
    // include_uploads=false only server-side; client-side the toggle alone
    // stops counting bytes against the cap).
    await userEvent.click(screen.getByRole("switch", { name: /include uploaded files/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).not.toBeDisabled());
  });

  it("sends each tool's filters with the estimate and the export, archived left out by default", async () => {
    const estimates: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/exports/estimate", ({ request }) => {
        estimates.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          ...ESTIMATE,
          tools: { ...ESTIMATE.tools, queue: { count: 6, disabled: false } },
        });
      })
    );
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />
    );
    await user.click(screen.getByRole("button", { name: /importable backup/i }));
    await screen.findByText("3 items");

    // A calendar search, with the archive left on its default, "All".
    const calendar = screen.getByRole("group", { name: "Calendar" });
    await user.click(within(calendar).getByRole("button", { name: "Filter Calendar" }));
    expect(within(calendar).getByRole("radio", { name: "All" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    await user.type(within(calendar).getByLabelText("Name or description"), "standup");

    // Live projects only.
    const projects = screen.getByRole("group", { name: "Projects" });
    await user.click(within(projects).getByRole("button", { name: "Filter Projects" }));
    await user.click(within(projects).getByRole("radio", { name: "Active" }));

    // Stopped queues, by the queue list's own status filter.
    const queues = screen.getByRole("group", { name: "Queues" });
    await user.click(within(queues).getByRole("button", { name: "Filter Queues" }));
    await user.click(within(queues).getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "Inactive" }));

    const expected = {
      calendar: { search: "standup" },
      project: { archived: false },
      queue: { is_active: false },
    };
    await waitFor(() =>
      expect(JSON.parse(estimates.at(-1)?.get("filters") ?? "null")).toEqual(expected)
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Calendar: “standup”")).toBeInTheDocument();
    expect(screen.getByText("Projects: Active only")).toBeInTheDocument();
    expect(screen.getByText("Queues: 1 more filter")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /start export/i }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(JSON.parse(sent!.searchParams.get("filters")!)).toEqual(expected);
  });

  it("narrows projects and files by templates, and files to untagged ones", async () => {
    const estimates: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/exports/estimate", ({ request }) => {
        estimates.push(new URL(request.url).searchParams);
        return HttpResponse.json(ESTIMATE);
      })
    );
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard scope={{ kind: "community" }} open onOpenChange={() => {}} />
    );
    await user.click(screen.getByRole("button", { name: /importable backup/i }));
    await screen.findByText("3 items");

    const projects = screen.getByRole("group", { name: "Projects" });
    await user.click(within(projects).getByRole("button", { name: "Filter Projects" }));
    await user.click(
      within(within(projects).getByRole("radiogroup", { name: "Templates" })).getByRole("radio", {
        name: "Templates only",
      })
    );

    const files = screen.getByRole("group", { name: "Files" });
    await user.click(within(files).getByRole("button", { name: "Filter Files" }));
    await user.click(
      within(within(files).getByRole("radiogroup", { name: "Templates" })).getByRole("radio", {
        name: "Without templates",
      })
    );
    await user.click(within(files).getByRole("switch", { name: "Untagged only" }));

    const expected = {
      project: { is_template: true },
      file: { is_template: false, untagged: true },
    };
    await waitFor(() =>
      expect(JSON.parse(estimates.at(-1)?.get("filters") ?? "null")).toEqual(expected)
    );
    expect(within(files).getByRole("button", { name: "Filter Files" })).toHaveTextContent("2");

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Projects: Templates only")).toBeInTheDocument();
    expect(screen.getByText("Files: Without templates · Untagged only")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /start export/i }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(JSON.parse(sent!.searchParams.get("filters")!)).toEqual(expected);
  });

  it("narrows each project's tasks by the task list's filters", async () => {
    const estimates: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/exports/estimate", ({ request }) => {
        estimates.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          ...ESTIMATE,
          tools: { ...ESTIMATE.tools, queue: { count: 6, disabled: false } },
        });
      })
    );
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard scope={{ kind: "initiative", initiativeId: 5 }} open onOpenChange={() => {}} />
    );
    await user.click(screen.getByRole("button", { name: /importable backup/i }));
    await screen.findByText("3 items");

    // Done tasks due this week, archived ones left out.
    const projects = screen.getByRole("group", { name: "Projects" });
    await user.click(within(projects).getByRole("button", { name: "Filter Projects" }));
    await user.click(within(projects).getByRole("combobox", { name: "Filter by status" }));
    await user.click(await screen.findByRole("option", { name: "Done" }));
    await user.keyboard("{Escape}");
    await user.click(within(projects).getByRole("combobox", { name: "Due filter" }));
    await user.click(await screen.findByRole("option", { name: "Due next 7 days" }));
    await user.click(within(projects).getByRole("switch", { name: "Show archived" }));

    const expected = {
      project: {
        tasks: {
          conditions: JSON.stringify(
            taskSpecConditions({
              ...EMPTY_TASK_FILTERS,
              status_categories: ["done"],
              due: "7_days",
            })
          ),
          include_archived: false,
        },
      },
    };
    await waitFor(() =>
      expect(JSON.parse(estimates.at(-1)?.get("filters") ?? "null")).toEqual(expected)
    );
    expect(within(projects).getByRole("button", { name: "Filter Projects" })).toHaveTextContent(
      "1"
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByText("Projects: Tasks (1 status, Due next 7 days, without archived)")
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /start export/i }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(JSON.parse(sent!.searchParams.get("filters")!)).toEqual(expected);
  });

  it("exports named calendars in the chosen format, narrowed to a date range", async () => {
    let sent: URLSearchParams | null = null;
    server.use(
      communityHttp.get("/exports/calendar", ({ request }) => {
        sent = new URL(request.url).searchParams;
        return new HttpResponse("BEGIN:VCALENDAR", {
          headers: { "Content-Type": "text/calendar" },
        });
      })
    );
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard
        scope={{
          kind: "entities",
          tool: Tool.calendar,
          ids: [4, 5],
          formats: TOOL_EXPORT_FORMATS[Tool.calendar] ?? [],
          filenameStem: "calendars",
        }}
        open
        onOpenChange={() => {}}
      />
    );

    await user.click(screen.getByRole("button", { name: "iCalendar (.ics)" }));
    await user.click(screen.getByLabelText("Event dates"));
    await user.click(await screen.findByRole("button", { name: "This month" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.getAll("ids")).toEqual(["4", "5"]);
    expect(sent!.get("format")).toBe("ics");
    // Only the content key travels: the ids already say which calendars.
    const now = new Date();
    expect(JSON.parse(sent!.get("filters")!)).toEqual({
      events: dateRangeParams({ from: startOfMonth(now), until: startOfDay(endOfMonth(now)) }),
    });
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
  });

  it("exports named projects in the chosen format, narrowed to the filtered tasks", async () => {
    let sent: URLSearchParams | null = null;
    server.use(
      communityHttp.get("/exports/project", ({ request }) => {
        sent = new URL(request.url).searchParams;
        return new HttpResponse("a,b", { headers: { "Content-Type": "text/csv" } });
      })
    );
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard
        scope={{
          kind: "entities",
          tool: Tool.project,
          ids: [3],
          formats: TOOL_EXPORT_FORMATS[Tool.project] ?? [],
          filenameStem: "projects",
        }}
        open
        onOpenChange={() => {}}
      />
    );

    await user.click(screen.getByRole("button", { name: "CSV" }));
    expect(screen.getByText("Choose which tasks to export")).toBeInTheDocument();
    // A report leaves archived tasks out, as its task list does, until asked.
    expect(screen.getByRole("switch", { name: "Show archived" })).not.toBeChecked();
    await user.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await user.click(await screen.findByRole("option", { name: "To do" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Tasks (1 status)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.getAll("ids")).toEqual(["3"]);
    expect(sent!.get("format")).toBe("csv");
    expect(JSON.parse(sent!.get("filters")!)).toEqual({
      tasks: {
        conditions: JSON.stringify(
          taskSpecConditions({ ...EMPTY_TASK_FILTERS, status_categories: ["todo"] })
        ),
        include_archived: false,
      },
    });
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
  });

  it("starts a project's export from the exporting person's own view of it", async () => {
    let sent: URLSearchParams | null = null;
    server.use(
      communityHttp.get("/exports/project", ({ request }) => {
        sent = new URL(request.url).searchParams;
        return new HttpResponse("a,b", { headers: { "Content-Type": "text/csv" } });
      })
    );
    const user = userEvent.setup();
    const tasks = {
      ...EMPTY_TASK_FILTERS,
      status_categories: ["done" as const],
      include_archived: true,
    };
    const taskSorting = [{ field: "status_position", dir: "asc" as const }];

    renderWithProviders(
      <ExportWizard
        scope={{
          kind: "entities",
          tool: Tool.project,
          ids: [3],
          formats: TOOL_EXPORT_FORMATS[Tool.project] ?? [],
          filenameStem: "projects",
          content: {
            tasks,
            taskSorting,
            taskColumns: ["title", "priority"],
            taskStatuses: buildDefaultTaskStatuses(3),
          },
        }}
        open
        onOpenChange={() => {}}
      />
    );

    await user.click(screen.getByRole("button", { name: "CSV" }));
    expect(screen.getByRole("switch", { name: "Show archived" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Tasks (1 status, with archived)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(JSON.parse(sent!.get("filters")!)).toEqual({
      tasks: {
        conditions: JSON.stringify(taskSpecConditions(tasks)),
        sorting: JSON.stringify(taskSorting),
        columns: ["title", "priority"],
        include_archived: true,
      },
    });
  });

  it("goes from format to confirm for a tool whose content has no filter", async () => {
    let sent: URLSearchParams | null = null;
    server.use(
      communityHttp.get("/exports/queue", ({ request }) => {
        sent = new URL(request.url).searchParams;
        return new HttpResponse("a,b", { headers: { "Content-Type": "text/csv" } });
      })
    );
    const drawPicture = vi.fn();
    const onOpenChange = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <ExportWizard
        scope={{
          kind: "entities",
          tool: Tool.queue,
          ids: [7],
          formats: TOOL_EXPORT_FORMATS[Tool.queue] ?? [],
          filenameStem: "queues",
          extraActions: [{ labelKey: "export.formatPng", onSelect: drawPicture }],
        }}
        open
        onOpenChange={onOpenChange}
      />
    );

    // The menu's grouping: the envelope is the backup, everything else a
    // report — the client-side picture included, which closes the wizard.
    expect(screen.getByText("Backup")).toBeInTheDocument();
    expect(screen.getByText("Report")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "PNG image" }));
    expect(drawPicture).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);

    await user.click(screen.getByRole("button", { name: "CSV" }));
    await user.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.getAll("ids")).toEqual(["7"]);
    expect(sent!.get("format")).toBe("csv");
    expect(sent!.get("filters")).toBeNull();
  });
});
