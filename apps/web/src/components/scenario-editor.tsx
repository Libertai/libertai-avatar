"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  emptyScenario,
  fetchMcpServers,
  saveScenario,
  slugify,
  testMcpServer,
  type McpServer,
  type Scenario
} from "../lib/scenarios";
import { fetchServerVoices, type ServerVoice } from "../lib/tts";
import styles from "../app/scenarios/scenarios.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function ScenarioEditor({ initial }: { initial?: Scenario }) {
  const router = useRouter();
  const [scenario, setScenario] = useState<Scenario>(initial ?? emptyScenario());
  const [dataText, setDataText] = useState(JSON.stringify(initial?.data ?? {}, null, 2));
  const [dataError, setDataError] = useState<string | null>(null);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<Record<string, string[]>>({});
  const [voices, setVoices] = useState<ServerVoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const isNew = !initial;

  useEffect(() => {
    fetchMcpServers(API_BASE_URL).then(setServers).catch(() => setServers([]));
    fetchServerVoices(API_BASE_URL).then(setVoices).catch(() => setVoices([]));
  }, []);

  // Discover each selected server's tools so the allowlist is a checklist, not a memory test.
  useEffect(() => {
    for (const name of scenario.mcp) {
      if (tools[name]) {
        continue;
      }
      testMcpServer(API_BASE_URL, name)
        .then((result) => setTools((current) => ({ ...current, [name]: result.tools.map((t) => t.name) })))
        .catch(() => setTools((current) => ({ ...current, [name]: [] })));
    }
  }, [scenario.mcp, tools]);

  function update(patch: Partial<Scenario>) {
    setScenario((current) => ({ ...current, ...patch }));
  }

  function onDataChange(text: string) {
    setDataText(text);
    try {
      const parsed = JSON.parse(text || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setDataError("The dataset must be a JSON object.");
        return;
      }
      update({ data: parsed as Record<string, unknown> });
      setDataError(null);
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Invalid JSON.");
    }
  }

  function toggleServer(name: string) {
    const selected = scenario.mcp.includes(name);
    const mcp = selected ? scenario.mcp.filter((item) => item !== name) : [...scenario.mcp, name];
    // Drop allowlisted tools that belonged to a server that is no longer selected.
    const available = new Set(mcp.flatMap((server) => tools[server] ?? []));
    const kept = scenario.tools?.filter((tool) => available.has(tool)) ?? [];
    // An empty list means "allow nothing" on the API; null is what means "allow all".
    update({ mcp, tools: kept.length > 0 ? kept : null });
  }

  function toggleTool(name: string) {
    const current = scenario.tools ?? [];
    const next = current.includes(name) ? current.filter((tool) => tool !== name) : [...current, name];
    update({ tools: next.length > 0 ? next : null });
  }

  async function onSave(event: React.FormEvent) {
    event.preventDefault();
    if (dataError) {
      setError("Fix the dataset JSON before saving.");
      return;
    }

    setSaving(true);
    try {
      const slug = scenario.slug || slugify(scenario.name);
      await saveScenario(API_BASE_URL, { ...scenario, slug });
      router.push("/scenarios");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  const selectedTools = scenario.tools ?? [];
  const allTools = scenario.mcp.flatMap((server) => (tools[server] ?? []).map((tool) => ({ server, tool })));

  return (
    <main className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/">Avatar</Link>
        <Link href="/scenarios">Scenarios</Link>
        <Link href="/scenarios/servers">MCP servers</Link>
      </nav>

      <div className={styles.top}>
        <div>
          <h1>{isNew ? "New scenario" : scenario.name}</h1>
          <p className={styles.lede}>
            The rules and dataset stay on the server. A visitor only ever receives the name, voice, language and
            greeting.
          </p>
        </div>
      </div>

      {error ? <div className={styles.failure}>{error}</div> : null}

      <form className={styles.form} onSubmit={onSave}>
        <div className={styles.row}>
          <label className={styles.field}>
            Name
            <input
              value={scenario.name}
              onChange={(event) => {
                const name = event.target.value;
                update(isNew ? { name, slug: slugify(name) } : { name });
              }}
              required
              maxLength={120}
            />
          </label>
          <label className={styles.field}>
            Link
            <input
              className={styles.mono}
              value={scenario.slug}
              onChange={(event) => update({ slug: slugify(event.target.value) })}
              required
              pattern="[a-z0-9][a-z0-9-]*"
            />
            <small>/s/{scenario.slug || "…"}</small>
          </label>
        </div>

        <label className={styles.field}>
          Description
          <input
            value={scenario.description}
            onChange={(event) => update({ description: event.target.value })}
            maxLength={500}
            placeholder="What this avatar does, shown on the scenario card."
          />
        </label>

        <div className={styles.row}>
          <label className={styles.field}>
            Language
            <input
              value={scenario.language}
              onChange={(event) => update({ language: event.target.value })}
              placeholder="en-US"
            />
            <small>Sets the voice, the microphone, and the reply language.</small>
          </label>
          <label className={styles.field}>
            Voice
            <select value={scenario.voice ?? ""} onChange={(event) => update({ voice: event.target.value || null })}>
              <option value="">Browser default</option>
              {voices.map((voice) => (
                <option key={voice.id} value={voice.id}>
                  {voice.name} — {voice.language} ({voice.quality})
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            Speech speed
            <input
              type="number"
              min={0.5}
              max={2}
              step={0.05}
              value={scenario.speed}
              onChange={(event) => update({ speed: Number(event.target.value) })}
            />
          </label>
        </div>

        <label className={styles.field}>
          Avatar VRM URL
          <input
            className={styles.mono}
            value={scenario.avatar ?? ""}
            onChange={(event) => update({ avatar: event.target.value || null })}
            placeholder="Leave empty for the default avatar"
          />
        </label>

        <label className={styles.field}>
          Greeting
          <input
            value={scenario.greeting}
            onChange={(event) => update({ greeting: event.target.value })}
            maxLength={1000}
            placeholder="The first line the visitor sees."
          />
        </label>

        <label className={styles.field}>
          Rules
          <textarea
            value={scenario.rules}
            onChange={(event) => update({ rules: event.target.value })}
            rows={12}
            placeholder="Who the avatar is, what it must collect, and what it must never do."
          />
          <small>
            Be explicit about what it must never invent. Everything here is private to the server.
          </small>
        </label>

        <label className={styles.field}>
          Dataset (JSON)
          <textarea
            className={styles.mono}
            value={dataText}
            onChange={(event) => onDataChange(event.target.value)}
            rows={12}
            spellCheck={false}
          />
          {dataError ? (
            <small style={{ color: "#ffb4b4" }}>{dataError}</small>
          ) : (
            <small>Facts the avatar may quote: menus, prices, policies. Injected whole into the prompt.</small>
          )}
        </label>

        <div className={styles.field}>
          MCP servers
          <div className={styles.serverList}>
            {servers.length === 0 ? (
              <small>
                None registered. <Link href="/scenarios/servers">Add one</Link> for live data.
              </small>
            ) : (
              servers.map((server) => (
                <label className={styles.serverRow} key={server.name}>
                  <input
                    type="checkbox"
                    checked={scenario.mcp.includes(server.name)}
                    onChange={() => toggleServer(server.name)}
                  />
                  <strong>{server.name}</strong>
                  <span>{server.description || server.url || server.command}</span>
                </label>
              ))
            )}
          </div>
        </div>

        {allTools.length > 0 ? (
          <div className={styles.field}>
            Allowed tools
            <div className={styles.toolGrid}>
              {allTools.map(({ server, tool }) => (
                <label className={styles.toolToggle} key={`${server}.${tool}`}>
                  <input
                    type="checkbox"
                    checked={selectedTools.includes(tool)}
                    onChange={() => toggleTool(tool)}
                  />
                  {tool}
                </label>
              ))}
            </div>
            <small>
              {selectedTools.length === 0
                ? "Nothing selected: every tool on the chosen servers is allowed."
                : `${selectedTools.length} tool(s) allowed. Everything else is refused.`}
            </small>
          </div>
        ) : null}

        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={scenario.published}
            onChange={(event) => update({ published: event.target.checked })}
          />
          Published — listed publicly. Drafts stay reachable by direct link.
        </label>

        <div className={styles.footer}>
          <button className={styles.buttonPrimary} type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save scenario"}
          </button>
          <Link className={styles.button} href="/scenarios">
            Cancel
          </Link>
          {!isNew ? (
            <Link className={styles.button} href={`/s/${scenario.slug}`}>
              Open
            </Link>
          ) : null}
        </div>
      </form>
    </main>
  );
}
