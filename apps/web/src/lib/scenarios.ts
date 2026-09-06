export type ScenarioSummary = {
  slug: string;
  name: string;
  description: string;
  language: string;
  voice: string | null;
  avatar: string | null;
  greeting: string;
  speed: number;
  collect: string[];
};

export type Scenario = ScenarioSummary & {
  rules: string;
  data: Record<string, unknown>;
  mcp: string[];
  tools: string[] | null;
  model: string | null;
  published: boolean;
  search: boolean;
};

export type McpServer = {
  name: string;
  description: string;
  transport: "stdio" | "http" | "sse";
  url: string | null;
  command: string | null;
  args: string[];
  headers: Record<string, string>;
  env: Record<string, string>;
};

export type ConnectionTest = {
  ok: boolean;
  detail: string;
  tools: { name: string; description: string }[];
};

const TOKEN_KEY = "avatar-admin-token";

export function adminToken(): string {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // A blocked storage API only costs the convenience of remembering the token.
  }
}

async function request<T>(apiBaseUrl: string, path: string, init: RequestInit = {}): Promise<T> {
  const token = adminToken();
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { "X-Admin-Token": token } : {}),
      ...init.headers
    }
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(detailToMessage(body.detail) ?? `Request failed with ${response.status}`);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** FastAPI returns a string for our errors and a list of objects for validation failures. */
function detailToMessage(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const entry = item as { loc?: unknown[]; msg?: string };
        const field = entry.loc?.slice(1).join(".") ?? "";
        return field ? `${field}: ${entry.msg}` : entry.msg;
      })
      .join("; ");
  }
  return null;
}

/** Whether the API requires an admin token. Readable without one, unlike /admin/scenarios. */
export async function fetchAdminProtection(apiBaseUrl: string): Promise<boolean> {
  const data = await request<{ admin_protected?: boolean }>(apiBaseUrl, "/health");
  return data.admin_protected ?? false;
}

export async function fetchScenario(apiBaseUrl: string, slug: string): Promise<ScenarioSummary> {
  return request<ScenarioSummary>(apiBaseUrl, `/scenarios/${slug}`);
}

export async function fetchScenarios(apiBaseUrl: string): Promise<ScenarioSummary[]> {
  const data = await request<{ scenarios?: ScenarioSummary[] }>(apiBaseUrl, "/scenarios");
  return data.scenarios ?? [];
}

export async function fetchAdminScenarios(
  apiBaseUrl: string
): Promise<{ scenarios: Scenario[]; protected: boolean }> {
  const data = await request<{ scenarios?: Scenario[]; protected?: boolean }>(apiBaseUrl, "/admin/scenarios");
  return { scenarios: data.scenarios ?? [], protected: data.protected ?? false };
}

export async function fetchAdminScenario(apiBaseUrl: string, slug: string): Promise<Scenario> {
  return request<Scenario>(apiBaseUrl, `/admin/scenarios/${slug}`);
}

export async function saveScenario(apiBaseUrl: string, scenario: Scenario): Promise<Scenario> {
  return request<Scenario>(apiBaseUrl, `/admin/scenarios/${scenario.slug}`, {
    method: "PUT",
    body: JSON.stringify(scenario)
  });
}

export async function deleteScenario(apiBaseUrl: string, slug: string): Promise<void> {
  await request<void>(apiBaseUrl, `/admin/scenarios/${slug}`, { method: "DELETE" });
}

export async function duplicateScenario(apiBaseUrl: string, slug: string): Promise<Scenario> {
  return request<Scenario>(apiBaseUrl, `/admin/scenarios/${slug}/duplicate`, { method: "POST" });
}

export async function fetchMcpServers(apiBaseUrl: string): Promise<McpServer[]> {
  const data = await request<{ servers?: McpServer[] }>(apiBaseUrl, "/mcp-servers");
  return data.servers ?? [];
}

export async function saveMcpServer(apiBaseUrl: string, server: McpServer): Promise<McpServer> {
  return request<McpServer>(apiBaseUrl, `/mcp-servers/${server.name}`, {
    method: "PUT",
    body: JSON.stringify(server)
  });
}

export async function deleteMcpServer(apiBaseUrl: string, name: string): Promise<void> {
  await request<void>(apiBaseUrl, `/mcp-servers/${name}`, { method: "DELETE" });
}

export async function testMcpServer(apiBaseUrl: string, name: string): Promise<ConnectionTest> {
  return request<ConnectionTest>(apiBaseUrl, `/mcp-servers/${name}/test`, { method: "POST" });
}

export function emptyScenario(): Scenario {
  return {
    slug: "",
    name: "",
    description: "",
    language: "en-US",
    voice: null,
    avatar: null,
    greeting: "",
    speed: 1,
    collect: [],
    rules: "",
    data: {},
    mcp: [],
    tools: null,
    model: null,
    published: false,
    search: false
  };
}

/** Turn a name into a URL slug, so an author never has to think about the link. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}
