"use client";

import { use, useEffect, useState } from "react";
import AvatarChat from "../../../components/avatar-chat";
import { fetchScenario, type ScenarioSummary } from "../../../lib/scenarios";
import styles from "../../page.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function ScenarioPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [scenario, setScenario] = useState<ScenarioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchScenario(API_BASE_URL, slug)
      .then(setScenario)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Scenario unavailable."));
  }, [slug]);

  if (error) {
    return (
      <main className={styles.shell}>
        <div className={styles.error}>{error}</div>
      </main>
    );
  }

  if (!scenario) {
    return <main className={styles.shell} />;
  }

  return <AvatarChat scenario={scenario} />;
}
