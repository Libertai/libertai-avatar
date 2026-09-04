"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  adminToken,
  deleteScenario,
  duplicateScenario,
  fetchAdminScenarios,
  saveScenario,
  setAdminToken,
  type Scenario
} from "../../lib/scenarios";
import styles from "./scenarios.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [protectedApi, setProtectedApi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { scenarios: loaded, protected: isProtected } = await fetchAdminScenarios(API_BASE_URL);
      setScenarios(loaded);
      setProtectedApi(isProtected);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load scenarios.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work.");
    }
  }

  async function copyLink(slug: string) {
    const link = `${window.location.origin}/s/${slug}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(slug);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      // Clipboard access can be denied; the link is visible on the card anyway.
      setError(`Copy failed. The link is ${link}`);
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
          <h1>Scenarios</h1>
          <p className={styles.lede}>
            Each scenario is an avatar with its own rules, dataset, voice and tools, reachable at its own link.
            Send a client the link and they talk to it — no login, no explanation.
          </p>
        </div>
        <div className={styles.actions}>
          <Link className={styles.buttonPrimary} href="/scenarios/new">
            New scenario
          </Link>
        </div>
      </div>

      {!protectedApi ? (
        <div className={styles.warning}>
          <strong>Editing is unprotected.</strong> Anyone who can reach this API can change these scenarios. Set{" "}
          <code>ADMIN_TOKEN</code> on the server before putting it on a network.
        </div>
      ) : (
        <AdminTokenBar onSaved={refresh} />
      )}

      {error ? <div className={styles.failure}>{error}</div> : null}

      {loading ? null : scenarios.length === 0 ? (
        <div className={styles.empty}>
          No scenarios yet. <Link href="/scenarios/new">Create the first one</Link>.
        </div>
      ) : (
        <div className={styles.grid}>
          {scenarios.map((scenario) => (
            <article className={styles.card} key={scenario.slug}>
              <div className={styles.cardTop}>
                <h2>{scenario.name}</h2>
                {!scenario.published ? <span className={`${styles.tag} ${styles.tagDraft}`}>Draft</span> : null}
              </div>
              <p>{scenario.description || "No description yet."}</p>
              <div className={styles.tags}>
                <span className={styles.tag}>{scenario.language}</span>
                {scenario.voice ? <span className={styles.tag}>{scenario.voice}</span> : null}
                {scenario.mcp.map((server) => (
                  <span className={styles.tag} key={server}>
                    ⚙ {server}
                  </span>
                ))}
              </div>
              <div className={styles.cardActions}>
                <Link className={styles.buttonPrimary} href={`/s/${scenario.slug}`}>
                  Open
                </Link>
                <Link className={styles.button} href={`/scenarios/${scenario.slug}`}>
                  Edit
                </Link>
                <button className={styles.button} type="button" onClick={() => void copyLink(scenario.slug)}>
                  {copied === scenario.slug ? "Copied" : "Copy link"}
                </button>
                <button
                  className={styles.button}
                  type="button"
                  onClick={() => void act(() => duplicateScenario(API_BASE_URL, scenario.slug))}
                >
                  Duplicate
                </button>
                <button
                  className={styles.button}
                  type="button"
                  onClick={() =>
                    void act(() => saveScenario(API_BASE_URL, { ...scenario, published: !scenario.published }))
                  }
                >
                  {scenario.published ? "Unpublish" : "Publish"}
                </button>
                <button
                  className={styles.buttonDanger}
                  type="button"
                  onClick={() => {
                    if (window.confirm(`Delete "${scenario.name}"? This cannot be undone.`)) {
                      void act(() => deleteScenario(API_BASE_URL, scenario.slug));
                    }
                  }}
                >
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}

function AdminTokenBar({ onSaved }: { onSaved: () => void }) {
  const [token, setToken] = useState("");

  useEffect(() => {
    setToken(adminToken());
  }, []);

  return (
    <div className={styles.notice}>
      <label className={styles.field}>
        Admin token
        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          onBlur={() => {
            setAdminToken(token);
            onSaved();
          }}
          placeholder="Required to edit scenarios"
          autoComplete="off"
        />
        <small>Kept in this browser only, and sent as X-Admin-Token.</small>
      </label>
    </div>
  );
}
