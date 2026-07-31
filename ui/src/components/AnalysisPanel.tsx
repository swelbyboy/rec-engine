import { useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import {
  fetchLiveJobs,
  getLiveRun,
  getLlmOnlyRun,
  getMindRun,
  listLiveRuns,
  listLlmOnlyRuns,
  listMindRuns,
} from "../lib/api";
import type { LiveJobSummary, LiveRecommendResult, MindRun, MindRunSummary } from "../types";

// Same validated categorical identity used everywhere a model/pipeline needs
// distinguishing on this page — run through dataviz's validate_palette.js
// (dark mode, surface #0b0c0d): lightness band / chroma floor / CVD
// separation / normal-vision floor / contrast all pass on the adjacent
// pairlist these charts use (funnel bars, matrix cells, distribution bars —
// never a scatter/bubble needing the stricter all-pairs guarantee).
const MODEL_COLORS: Record<string, string> = {
  "rec-engine PoC": "#3987e5",
  "Mind Live": "#d95926",
  "Mind Fixed": "#199e70",
  "LLM-only": "#c98500",
};
const MODEL_ORDER = ["rec-engine PoC", "Mind Live", "Mind Fixed", "LLM-only"];

// Verdict-tier colors reuse the app's existing convention (see VERDICT_STYLE
// in LiveCandidateCard.tsx / TIER_STYLE in MindCandidateCard.tsx) — these are
// STATUS colors (best→worst), a different encoding job than MODEL_COLORS'
// categorical identity, so they're deliberately a separate palette.
const TIER_COLORS: Record<string, string> = {
  strong: "#d5fa54",
  good: "#8ea1ff",
  possible: "#eab86b",
  weak: "rgba(255,255,255,0.35)",
  unscored: "rgba(255,255,255,0.12)",
};
const TIER_ORDER = ["strong", "good", "possible", "weak", "unscored"] as const;
const TIER_LABELS: Record<string, string> = {
  strong: "Strong",
  good: "Good",
  possible: "Possible",
  weak: "Weak",
  unscored: "Unscored",
};

// --- Normalizing two different verdict vocabularies onto one shared scale ---
// rec-engine/LLM-only: verdict field, strong_match|good_match|possible|weak_match.
// A "weak_match" whose rationale is the batch-failure placeholder (see
// funnel_rerank._merge_ranked_batches) never got a real judgment — bucketed
// separately as "unscored" rather than conflated with a genuine weak verdict.
function liveTier(c: { verdict: string; rationale?: string }): string {
  if ((c.rationale ?? "").includes("Not returned by the rerank stage")) return "unscored";
  if (c.verdict === "strong_match") return "strong";
  if (c.verdict === "good_match") return "good";
  if (c.verdict === "possible") return "possible";
  return "weak";
}

// Mind: reranker_tier is a free-text label ("Strong Match", "Good Match", …);
// hard_filter_pass=false or a null tier means it was never reached by Mind's
// own reranker at all.
function mindTier(c: { reranker_tier: string | null; hard_filter_pass: boolean | null }): string {
  const t = (c.reranker_tier ?? "").toLowerCase();
  if (c.hard_filter_pass === false || !t) return "unscored";
  if (t.includes("strong")) return "strong";
  if (t.includes("good")) return "good";
  if (t.includes("possible")) return "possible";
  return "weak";
}

interface VariantData {
  label: string;
  // Uniform 3-stage funnel so every variant draws from the same chart, even
  // though the underlying pipelines have different numbers of real stages —
  // see funnel_rerank.run_llm_only_pipeline (flat: nothing is filtered) vs
  // run_live_pipeline (constraint engine + triage) vs Mind's hard-filter gate.
  funnel: { universe: number; survivedFilter: number; ranked: number };
  tierCounts: Record<string, number>;
  topN: Set<string>; // top-20 candidate ids, for the overlap matrix
  runLabel: string; // e.g. "31/07 10:23 — v7-legacy-score-default"
}

function fromLiveResult(label: string, result: LiveRecommendResult, runLabel: string): VariantData {
  const tierCounts: Record<string, number> = {};
  for (const c of result.ranked) {
    const t = liveTier(c);
    tierCounts[t] = (tierCounts[t] ?? 0) + 1;
  }
  const scored = result.ranked.filter((c) => liveTier(c) !== "unscored");
  return {
    label,
    funnel: {
      universe: result.candidates_considered,
      survivedFilter: result.candidates_passed_filter,
      ranked: scored.length,
    },
    tierCounts,
    topN: new Set(scored.slice(0, 20).map((c) => c.candidate_id)),
    runLabel,
  };
}

function fromMindResult(label: string, result: MindRun, runLabel: string): VariantData {
  const tierCounts: Record<string, number> = {};
  for (const c of result.candidates) {
    const t = mindTier(c);
    tierCounts[t] = (tierCounts[t] ?? 0) + 1;
  }
  const survivedFilter = result.candidates.filter((c) => c.hard_filter_pass !== false).length;
  const ranked = result.candidates.filter((c) => c.reranker_rank != null);
  const top20 = ranked
    .slice()
    .sort((a, b) => (a.reranker_rank ?? 0) - (b.reranker_rank ?? 0))
    .slice(0, 20);
  return {
    label,
    funnel: { universe: result.candidates.length, survivedFilter, ranked: ranked.length },
    tierCounts,
    topN: new Set(top20.map((c) => String(c.candidate_id))),
    runLabel,
  };
}

function FunnelBar({ variant }: { variant: VariantData }) {
  const color = MODEL_COLORS[variant.label] ?? "#8ea1ff";
  const max = variant.funnel.universe || 1;
  const stages: [string, number][] = [
    // Mind's shortlist_run_candidates only ever stores candidates already
    // selected into Mind's OWN pool-construction step (computePool) — it
    // never records Mind's true upstream universe size before that pool was
    // built. So "Eligible pool" for rec-engine (the real eligible-candidate
    // count) and Mind (Mind's own already-narrowed audited pool) are not the
    // same concept — labeled differently so the chart doesn't imply they are.
    [variant.label.startsWith("Mind") ? "Considered (Mind's pool)" : "Eligible pool", variant.funnel.universe],
    ["Survived filtering", variant.funnel.survivedFilter],
    ["Ranked", variant.funnel.ranked],
  ];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />
        <span className="text-xs font-medium text-white">{variant.label}</span>
        <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>{variant.runLabel}</span>
      </div>
      {stages.map(([name, count]) => {
        const pct = Math.max((count / max) * 100, count > 0 ? 1.5 : 0);
        return (
          <div key={name} className="flex items-center gap-2">
            <span className="w-40 shrink-0 text-[10px] leading-tight" style={{ color: "rgba(255,255,255,0.45)" }}>{name}</span>
            <div className="h-4 flex-1 rounded" style={{ background: "rgba(255,255,255,0.05)" }}>
              <div
                className="h-4 rounded"
                style={{ width: `${pct}%`, background: color, minWidth: count > 0 ? 2 : 0 }}
              />
            </div>
            <span className="w-16 shrink-0 text-right text-[10px] font-mono" style={{ color: "rgba(255,255,255,0.6)" }}>
              {count.toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function TierDistributionBar({ variant }: { variant: VariantData }) {
  const total = TIER_ORDER.reduce((sum, t) => sum + (variant.tierCounts[t] ?? 0), 0) || 1;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-white">{variant.label}</span>
        <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.35)" }}>{total} scored</span>
      </div>
      <div className="flex h-4 w-full overflow-hidden rounded" style={{ background: "rgba(255,255,255,0.05)" }}>
        {TIER_ORDER.map((t, i) => {
          const count = variant.tierCounts[t] ?? 0;
          if (count === 0) return null;
          const pct = (count / total) * 100;
          return (
            <div
              key={t}
              title={`${TIER_LABELS[t]}: ${count} (${pct.toFixed(0)}%)`}
              style={{
                width: `${pct}%`,
                background: TIER_COLORS[t],
                marginLeft: i > 0 ? 2 : 0, // 2px surface gap between stacked segments
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

function OverlapMatrix({ variants }: { variants: VariantData[] }) {
  function overlapPct(a: VariantData, b: VariantData): number {
    if (a.topN.size === 0 || b.topN.size === 0) return 0;
    let hits = 0;
    for (const id of a.topN) if (b.topN.has(id)) hits++;
    return (hits / Math.min(a.topN.size, b.topN.size)) * 100;
  }
  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="w-24" />
            {variants.map((v) => (
              <th key={v.label} className="px-2 pb-1 text-[10px] font-medium" style={{ color: MODEL_COLORS[v.label] }}>
                {v.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {variants.map((row) => (
            <tr key={row.label}>
              <td className="pr-2 text-right text-[10px] font-medium" style={{ color: MODEL_COLORS[row.label] }}>
                {row.label}
              </td>
              {variants.map((col) => {
                const pct = overlapPct(row, col);
                // Sequential single-hue ramp (magnitude, 0-100%) — reuses the
                // blue categorical slot's hue family rather than introducing
                // a second ramp for one matrix.
                const alpha = 0.08 + (pct / 100) * 0.55;
                return (
                  <td
                    key={col.label}
                    className="h-10 w-16 rounded text-center text-[11px] font-mono"
                    style={{
                      background: `rgba(57,135,229,${alpha})`,
                      color: pct > 45 ? "#fff" : "rgba(255,255,255,0.6)",
                    }}
                    title={`${row.label} vs ${col.label}: ${pct.toFixed(0)}% of top-20 overlap`}
                  >
                    {pct.toFixed(0)}%
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>
        % of the smaller top-20 set also present in the other's top-20, for the currently-loaded run per column/row.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "rgba(255,255,255,0.08)", background: "#0b0c0d" }}>
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
        {title}
      </p>
      {children}
    </div>
  );
}

export default function AnalysisPanel() {
  const [jobs, setJobs] = useState<LiveJobSummary[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [variants, setVariants] = useState<VariantData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLiveJobs()
      .then((rows) => {
        setJobs(rows);
        if (rows.length > 0) setSelectedJobId(rows[0].job_order_id);
      })
      .catch((e) => setJobsError(e.message));
  }, []);

  useEffect(() => {
    if (selectedJobId == null) {
      setVariants([]);
      return;
    }
    setLoading(true);
    setError(null);

    const isFixedScorerVersion = (v?: string | null) => (v ?? "").includes("legacy-score");
    const runLabelFor = (r: { run_started_at: string; scorer_version?: string | null }) =>
      `${new Date(r.run_started_at).toLocaleString()} — ${r.scorer_version ?? "unknown"}`;
    const liveRunLabelFor = (r: { completed_at: string }) => new Date(r.completed_at).toLocaleString();

    Promise.all([
      listLiveRuns(selectedJobId).catch(() => []),
      listMindRuns(selectedJobId).catch(() => [] as MindRunSummary[]),
      listLlmOnlyRuns(selectedJobId).catch(() => []),
    ])
      .then(async ([liveRuns, mindRuns, llmOnlyRuns]) => {
        const results: VariantData[] = [];

        if (liveRuns.length > 0) {
          const r = await getLiveRun(liveRuns[0].run_id);
          results.push(fromLiveResult("rec-engine PoC", r, liveRunLabelFor(liveRuns[0])));
        }
        const mindLive = mindRuns.find((r) => !isFixedScorerVersion(r.scorer_version));
        const mindFixed = mindRuns.find((r) => isFixedScorerVersion(r.scorer_version));
        if (mindLive) {
          const r = await getMindRun(mindLive.run_id);
          results.push(fromMindResult("Mind Live", r, runLabelFor(mindLive)));
        }
        if (mindFixed) {
          const r = await getMindRun(mindFixed.run_id);
          results.push(fromMindResult("Mind Fixed", r, runLabelFor(mindFixed)));
        }
        if (llmOnlyRuns.length > 0) {
          const r = await getLlmOnlyRun(llmOnlyRuns[0].run_id);
          results.push(fromLiveResult("LLM-only", r, liveRunLabelFor(llmOnlyRuns[0])));
        }

        results.sort((a, b) => MODEL_ORDER.indexOf(a.label) - MODEL_ORDER.indexOf(b.label));
        setVariants(results);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load runs for this role."))
      .finally(() => setLoading(false));
  }, [selectedJobId]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-none flex items-center gap-3 border-b px-6 py-4" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="relative">
          <select
            value={selectedJobId ?? ""}
            onChange={(e) => setSelectedJobId(Number(e.target.value))}
            disabled={jobs.length === 0}
            className="appearance-none rounded-lg border pl-3 pr-8 py-2 text-sm font-medium outline-none"
            style={{ background: "#0b0c0d", borderColor: "rgba(255,255,255,0.12)", color: "white" }}
          >
            {jobs.map((j) => (
              <option key={j.job_order_id} value={j.job_order_id}>
                {j.job_title} — {j.company_name}
              </option>
            ))}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
            style={{ color: "rgba(255,255,255,0.4)" }}
          />
        </div>
        {jobsError && <span className="text-xs text-red-400">Failed to load roles: {jobsError}</span>}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && <p className="text-xs text-red-400">{error}</p>}
        {loading && (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin" style={{ color: "#d5fa54" }} />
          </div>
        )}
        {!loading && variants.length === 0 && !error && (
          <p className="text-xs" style={{ color: "rgba(255,255,255,0.3)" }}>
            No runs found for this role in any variant yet.
          </p>
        )}
        {!loading && variants.length > 0 && (
          <div className="flex flex-col gap-4">
            <Section title="Coverage funnel — eligible pool → survived filtering → ranked">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                {variants.map((v) => (
                  <FunnelBar key={v.label} variant={v} />
                ))}
              </div>
              <p className="mt-4 text-[10px] leading-relaxed" style={{ color: "rgba(255,255,255,0.3)" }}>
                Not directly comparable to rec-engine's "Eligible pool": Mind's{" "}
                <code>shortlist_run_candidates</code> only ever records candidates already selected
                into Mind's own pool-construction step — it doesn't expose how large Mind's true
                candidate universe was before that pool was built. "Considered (Mind's pool)" is a
                later-stage, already-narrowed number, not an apples-to-apples eligible-pool size.
              </p>
            </Section>

            <Section title="Verdict-tier distribution">
              <div className="flex flex-col gap-3">
                {variants.map((v) => (
                  <TierDistributionBar key={v.label} variant={v} />
                ))}
                <div className="mt-1 flex flex-wrap gap-3">
                  {TIER_ORDER.map((t) => (
                    <div key={t} className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-sm" style={{ background: TIER_COLORS[t] }} />
                      <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.4)" }}>{TIER_LABELS[t]}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Section>

            {variants.length > 1 && (
              <Section title="Top-20 overlap across variants">
                <OverlapMatrix variants={variants} />
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
