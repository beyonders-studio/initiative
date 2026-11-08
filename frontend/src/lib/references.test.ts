import { describe, expect, it } from "vitest";

import { buildInitiative } from "@/__tests__/factories";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { linkableToolTypes } from "@/lib/references";
import { TOOLS, toolViewPermission } from "@/lib/tools";

// Every master switch on, derived from the registry rather than listed: a new
// toggleable tool is switched on here the day it exists, so the "is the tools"
// case below keeps meaning what it says.
const allSwitchesOn = Object.fromEntries(TOOLS.map((tool) => [toolViewPermission(tool), true]));

const enabled = (overrides = {}) => buildInitiative({ ...allSwitchesOn, ...overrides });

describe("what [[ ]] can reach", () => {
  it("is the tools, derived from the enum", () => {
    expect(linkableToolTypes(enabled()).sort()).toEqual(Object.values(Tool).map(String).sort());
  });

  it("leaves out a tool this initiative switched off", () => {
    const types = linkableToolTypes(enabled({ counter_groups_enabled: false }));
    expect(types).not.toContain(SearchEntityType.counter_group);
    // The rest are untouched.
    expect(types).toContain(SearchEntityType.calendar);
  });

  it("keeps the core tools, which have no switch to turn off", () => {
    const types = linkableToolTypes(
      enabled({ counter_groups_enabled: false, calendars_enabled: false })
    );
    expect(types).toContain(SearchEntityType.project);
    expect(types).toContain(SearchEntityType.file);
  });

  it("never reaches what lives inside a tool", () => {
    // A task needs a project, an event needs a calendar and a time — neither
    // can be made from a name, so `#` is how you reach them.
    const types = linkableToolTypes(enabled());
    expect(types).not.toContain(SearchEntityType.task);
    expect(types).not.toContain(SearchEntityType.calendar_event);
    expect(types).not.toContain(SearchEntityType.tag);
  });
});
