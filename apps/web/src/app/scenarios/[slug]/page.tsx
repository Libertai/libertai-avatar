"use client";

import { use, useEffect, useState } from "react";
import ScenarioEditor from "../../../components/scenario-editor";
import { fetchAdminScenario, type Scenario } from "../../../lib/scenarios";
import styles from "../scenarios.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function EditScenarioPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAdminScenario(API_BASE_URL, slug)
      .then(setScenario)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load the scenario."));
  }, [slug]);

  if (error) {
    return (
      <main className={styles.page}>
        <div className={styles.failure}>{error}</div>
      </main>
    );
  }

  return scenario ? <ScenarioEditor initial={scenario} /> : <main className={styles.page} />;
}
