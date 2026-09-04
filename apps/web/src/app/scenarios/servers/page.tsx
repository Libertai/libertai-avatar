"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  deleteMcpServer,
  fetchMcpServers,
  saveMcpServer,
  testMcpServer,
  type ConnectionTest,
  type McpServer
} from "../../../lib/scenarios";
import styles from "../scenarios.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function blankServer(): McpServer {
  return {
    name: "",
    description: "",
    transport: "http",
    url: "",
    command: "",
    args: [],
    headers: {},
    env: {}
  };
}

export default function McpServersPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [draft, setDraft] = useState<McpServer | null>(null);
  const [results, setResults] = useState<Record<string, ConnectionTest>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setServers(await fetchMcpServers(API_BASE_URL));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load servers.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      await refresh();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work.");
    }
  }

  async function test(name: string) {
    try {
      setResults((current) => ({ ...current, [name]: { ok: false, detail: "Connecting…", tools: [] } }));
      const result = await testMcpServer(API_BASE_URL, name);
      setResults((current) => ({ ...current, [name]: result }));
    } catch (err) {
      setResults((current) => ({
        ...current,
        [name]: { ok: false, detail: err instanceof Error ? err.message : "Failed", tools: [] }
      }));
    }
  }

  return (
    <main className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/">Avatar</Link>
        <Link href="/scenarios">Scenarios</Link>
        <Link href="/scenarios/servers">MCP servers</Link>
      </nav>

      <div className={styles.top}>
        <div>
          <h1>MCP servers</h1>
          <p className={styles.lede}>
            Tools an avatar can call for live data — a booking system, a pricing service, anything that speaks MCP.
            Only registered servers can ever be contacted, and credentials are encrypted before they are stored.
          </p>
        </div>
        <div className={styles.actions}>
          <button className={styles.buttonPrimary} type="button" onClick={() => setDraft(blankServer())}>
            Register server
          </button>
        </div>
      </div>

      {error ? <div className={styles.failure}>{error}</div> : null}

      {draft ? (
        <ServerForm
          key={draft.name || "new-server"}
          server={draft}
          onCancel={() => setDraft(null)}
          onSave={async (server) => {
            await act(() => saveMcpServer(API_BASE_URL, server));
            setDraft(null);
          }}
        />
      ) : null}

      <div className={styles.grid}>
        {servers.map((server) => (
          <article className={styles.card} key={server.name}>
            <div className={styles.cardTop}>
              <h2>{server.name}</h2>
              <span className={styles.tag}>{server.transport}</span>
            </div>
            <p>{server.description || "No description."}</p>
            <code className={styles.mono} style={{ fontSize: 11, color: "#6f7d86", wordBreak: "break-all" }}>
              {server.transport === "stdio" ? `${server.command} ${server.args.join(" ")}` : server.url}
            </code>
            {results[server.name] ? (
              <div className={results[server.name]!.ok ? styles.notice : styles.failure} style={{ marginTop: 4 }}>
                {results[server.name]!.detail}
                {results[server.name]!.tools.length > 0 ? (
                  <div className={styles.tags} style={{ marginTop: 8 }}>
                    {results[server.name]!.tools.map((tool) => (
                      <span className={styles.tag} key={tool.name} title={tool.description}>
                        {tool.name}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className={styles.cardActions}>
              <button className={styles.button} type="button" onClick={() => void test(server.name)}>
                Test connection
              </button>
              <button className={styles.button} type="button" onClick={() => setDraft(server)}>
                Edit
              </button>
              <button
                className={styles.buttonDanger}
                type="button"
                onClick={() => {
                  if (window.confirm(`Remove "${server.name}"?`)) {
                    void act(() => deleteMcpServer(API_BASE_URL, server.name));
                  }
                }}
              >
                Remove
              </button>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

function ServerForm({
  server,
  onSave,
  onCancel
}: {
  server: McpServer;
  onSave: (server: McpServer) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<McpServer>(server);
  const [headerText, setHeaderText] = useState(
    Object.entries(server.headers)
      .map(([key, value]) => `${key}: ${value}`)
      .join("\n")
  );

  function update(patch: Partial<McpServer>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function parseHeaders(text: string): Record<string, string> {
    const headers: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const index = line.indexOf(":");
      if (index > 0) {
        headers[line.slice(0, index).trim()] = line.slice(index + 1).trim();
      }
    }
    return headers;
  }

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void onSave({ ...draft, headers: parseHeaders(headerText) });
      }}
    >
      <div className={styles.row}>
        <label className={styles.field}>
          Name
          <input
            className={styles.mono}
            value={draft.name}
            onChange={(event) => update({ name: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })}
            required
            pattern="[a-z0-9][a-z0-9_-]*"
          />
        </label>
        <label className={styles.field}>
          Transport
          <select
            value={draft.transport}
            onChange={(event) => update({ transport: event.target.value as McpServer["transport"] })}
          >
            <option value="http">http — remote server</option>
            <option value="sse">sse — older remote server</option>
            <option value="stdio">stdio — local process</option>
          </select>
        </label>
      </div>

      <label className={styles.field}>
        Description
        <input value={draft.description} onChange={(event) => update({ description: event.target.value })} />
      </label>

      {draft.transport === "stdio" ? (
        <div className={styles.row}>
          <label className={styles.field}>
            Command
            <input
              className={styles.mono}
              value={draft.command ?? ""}
              onChange={(event) => update({ command: event.target.value })}
              placeholder="python"
              required
            />
            <small>&quot;python&quot; runs on the API&apos;s own interpreter.</small>
          </label>
          <label className={styles.field}>
            Arguments
            <input
              className={styles.mono}
              value={draft.args.join(" ")}
              onChange={(event) => update({ args: event.target.value.split(" ").filter(Boolean) })}
              placeholder="apps/api/mcp_servers/pizzeria.py"
            />
          </label>
        </div>
      ) : (
        <>
          <label className={styles.field}>
            URL
            <input
              className={styles.mono}
              value={draft.url ?? ""}
              onChange={(event) => update({ url: event.target.value })}
              placeholder="https://mcp.example.com/mcp"
              required
            />
          </label>
          <label className={styles.field}>
            Headers
            <textarea
              className={styles.mono}
              value={headerText}
              onChange={(event) => setHeaderText(event.target.value)}
              rows={3}
              placeholder={"Authorization: Bearer ${AGENDA_TOKEN}"}
              spellCheck={false}
            />
            <small>
              One per line. A literal token is encrypted before it is stored and never sent back here. Write{" "}
              <code>{"${VAR}"}</code> to read it from the server environment instead.
            </small>
          </label>
        </>
      )}

      <div className={styles.footer}>
        <button className={styles.buttonPrimary} type="submit">
          Save server
        </button>
        <button className={styles.button} type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
