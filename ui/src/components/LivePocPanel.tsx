import { useEffect, useState } from "react";
import { ChevronDown, Loader2, RotateCcw } from "lucide-react";
import { fetchLiveJobs, runLiveRecommend } from "../lib/api";
import type { LiveJobSummary, LiveRecommendResult, LiveVerdict } from "../types";

const VERDICT_STYLE: Record<LiveVerdict, { bg: string; fg: string; label: string }> = {
  strong_match: { bg: "rgba(213,250,84,0.14)", fg: "#d5fa54", label: "Strong match" },
  good_match: { bg: "rgba(81,112,255,0.14)", fg: "#8ea1ff", label: "Good match" },
  possible: { bg: "rgba(217,119,6,0.14)", fg: "#eab86b", label: "Possible" },
  weak_match: { bg: "rgba(255,255,255,0.06)", fg: "rgba(255,255,255,0.45)", label: "Weak match" },
};

const FLEX_STYLE: Record<string, { fg: string; label: string }> = {
  rigid: { fg: "rgba(255,255,255,0.4)", label: "Rigid" },
  some_flex: { fg: "#eab86b", label: "Some flex" },
  likely_flexible: { fg: "#d5fa54", label: "Likely flexible" },
};

function VerdictBadge({ verdict }: { verdict: LiveVerdict }) {
  const s = VERDICT_STYLE[verdict];
  return (
    <span
      className="inline-flex shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

export default function LivePocPanel() {
  const [jobs, setJobs] = useState<LiveJobSummary[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<LiveRecommendResult | null>(null);
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
    if (!loading) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  async function handleRun() {
    if (selectedJobId == null) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runLiveRecommend({ job_order_id: selectedJobId, candidate_limit: 100, rerank_limit: 30 });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Controls */}
      <div className="flex-none flex items-center gap-3 border-b px-6 py-4" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="relative">
          <select
            value={selectedJobId ?? ""}
            onChange={(e) => setSelectedJobId(Number(e.target.value))}
            disabled={loading || jobs.length === 0}
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

        <button
          onClick={handleRun}
          disabled={loading || selectedJobId == null}
          className="rounded-lg px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-50"
          style={{ background: "#d5fa54", color: "#0b0c0d" }}
        >
          {loading ? (
            <span className="flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Running live pipeline… {elapsed}s
            </span>
          ) : (
            "Run live pipeline"
          )}
        </button>

        {result && !loading && (
          <button
            onClick={() => setResult(null)}
            className="flex items-center gap-1.5 text-xs transition-colors"
            style={{ color: "rgba(255,255,255,0.35)" }}
          >
            <RotateCcw className="h-3 w-3" />
            Clear
          </button>
        )}

        {jobsError && <span className="text-xs text-red-400">Failed to load open roles: {jobsError}</span>}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div className="mb-4 rounded-xl border px-4 py-3" style={{ background: "rgba(220,38,38,0.1)", borderColor: "rgba(220,38,38,0.25)" }}>
            <p className="text-sm font-medium text-red-400">Error</p>
            <p className="mt-0.5 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{error}</p>
          </div>
        )}

        {!result && !loading && !error && (
          <div className="flex h-48 items-center justify-center text-center text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>
            Pick a live open role and run the pipeline — reads live candidates/jobs from Mothership,
            filters via the constraint engine, then ranks via the coarse-then-fine LLM funnel.
          </div>
        )}

        {loading && (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-center text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "#d5fa54" }} />
            Extracting job requirements, filtering candidates, and ranking — this takes ~45-60s.
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-5">
            {/* Job header + stats */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                {result.job.company}
              </p>
              <h2 className="text-lg font-semibold text-white">{result.job.title}</h2>
              <p className="mt-2 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{result.coarse_brief.summary}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
                <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
                  {result.candidates_considered} considered
                </span>
                <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
                  {result.candidates_passed_filter} passed filter
                </span>
                <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
                  {result.eliminated.length} eliminated
                </span>
                <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
                  UK-based required: {result.coarse_brief.requires_uk_based}
                </span>
                <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
                  Sponsors visa: {result.coarse_brief.offers_visa_sponsorship}
                </span>
              </div>
            </div>

            {/* Flexibility notes */}
            {result.coarse_brief.flexibility_notes.length > 0 && (
              <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)" }}>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                  Constraint flexibility judgment
                </p>
                <div className="flex flex-col gap-1.5">
                  {result.coarse_brief.flexibility_notes.map((n, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span
                        className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
                        style={{ color: FLEX_STYLE[n.flex_judgment]?.fg ?? "rgba(255,255,255,0.4)", background: "rgba(255,255,255,0.05)" }}
                      >
                        {FLEX_STYLE[n.flex_judgment]?.label ?? n.flex_judgment}
                      </span>
                      <span style={{ color: "rgba(255,255,255,0.5)" }}>{n.constraint_description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ranked candidates */}
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Ranked candidates ({result.ranked.length})
              </p>
              <div className="flex flex-col gap-2">
                {result.ranked.map((c, i) => (
                  <div
                    key={c.candidate_id}
                    className="rounded-lg border p-3"
                    style={{ borderColor: "rgba(255,255,255,0.08)", background: "#111214" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono" style={{ color: "rgba(255,255,255,0.25)" }}>#{i + 1}</span>
                        <span className="text-sm font-medium text-white">{c.name}</span>
                        {c.flagged_for_review && (
                          <span className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase" style={{ background: "rgba(217,119,6,0.14)", color: "#eab86b" }}>
                            Flagged
                          </span>
                        )}
                      </div>
                      <VerdictBadge verdict={c.verdict} />
                    </div>
                    <p className="mt-1.5 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>{c.rationale}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Eliminated candidates */}
            {result.eliminated.length > 0 && (
              <div>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                  Eliminated ({result.eliminated.length})
                </p>
                <div className="flex flex-col gap-1.5">
                  {result.eliminated.map((c) => (
                    <div key={c.candidate_id} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
                      <p className="text-xs font-medium" style={{ color: "rgba(255,255,255,0.55)" }}>{c.name}</p>
                      {c.reasons.map((r, i) => (
                        <p key={i} className="mt-0.5 text-[11px]" style={{ color: "rgba(255,255,255,0.35)" }}>{r}</p>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
