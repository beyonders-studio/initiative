import {
  MetadataType,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildPropertyDefinition(
  overrides: Partial<PropertyDefinitionRead> = {}
): PropertyDefinitionRead {
  counter++;
  return {
    id: counter,
    initiative_id: 1,
    name: "Priority",
    type: MetadataType.text,
    position: 0,
    color: null,
    options: null,
    currency: null,
    project_id: null,
    collection_id: null,
    created_at: "2026-04-22T00:00:00.000Z",
    updated_at: "2026-04-22T00:00:00.000Z",
    ...overrides,
  };
}

export function buildPropertyOption(overrides: Partial<PropertyOption> = {}): PropertyOption {
  return {
    value: "draft",
    label: "Draft",
    color: null,
    ...overrides,
  };
}

export function buildPropertySummary(overrides: Partial<PropertySummary> = {}): PropertySummary {
  counter++;
  return {
    property_id: counter,
    name: `Property ${counter}`,
    type: MetadataType.text,
    project_id: null,
    collection_id: null,
    install_id: null,
    key: null,
    options: null,
    currency: null,
    value: "",
    ...overrides,
  };
}
