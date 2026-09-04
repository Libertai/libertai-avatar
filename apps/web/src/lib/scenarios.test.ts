import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchScenario, fetchScenarios, slugify } from "./scenarios";

afterEach(() => {
  vi.restoreAllMocks();
});

const PIZZERIA = {
  slug: "pizzeria",
  name: "Tony's Pizzeria",
  description: "Takes phone orders.",
  language: "en-US",
  voice: "en_US-ryan-high",
  avatar: null,
  greeting: "Tony's Pizzeria!"
};

describe("fetchScenario", () => {
  it("returns the scenario summary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => PIZZERIA }));

    await expect(fetchScenario("http://localhost:8000", "pizzeria")).resolves.toEqual(PIZZERIA);
  });

  it("surfaces the backend detail for an unknown scenario", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: "Unknown scenario 'nope'." }) })
    );

    await expect(fetchScenario("http://localhost:8000", "nope")).rejects.toThrow("Unknown scenario");
  });
});

describe("fetchScenarios", () => {
  it("returns the catalogue", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ scenarios: [PIZZERIA] }) }));

    await expect(fetchScenarios("http://localhost:8000")).resolves.toEqual([PIZZERIA]);
  });

  it("treats a missing field as empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));

    await expect(fetchScenarios("http://localhost:8000")).resolves.toEqual([]);
  });
});

describe("slugify", () => {
  it("makes a URL-safe slug from a name", () => {
    expect(slugify("Tony's Pizzeria")).toBe("tony-s-pizzeria");
    expect(slugify("  Clinique Saint-Jean  ")).toBe("clinique-saint-jean");
  });

  it("strips accents so the link stays ASCII", () => {
    expect(slugify("Café Crème")).toBe("cafe-creme");
  });

  it("returns an empty slug for a name with nothing usable", () => {
    expect(slugify("!!!")).toBe("");
  });
});
