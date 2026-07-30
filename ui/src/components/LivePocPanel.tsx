import { useEffect, useState } from "react";
import { ChevronDown, Loader2, RotateCcw } from "lucide-react";
import { fetchLiveJobs, getLiveRun, listLiveRuns, runLiveRecommend } from "../lib/api";
import LiveCandidateList from "./LiveCandidateList";
import LiveRolePane from "./LiveRolePane";
import type { LiveJobSummary, LiveRecommendResult, LiveRunSummary } from "../types";

export default function LivePocPanel() {
  const [jobs, setJobs] = useState<LiveJobSummary[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const [runs, setRuns] = useState<LiveRunSummary[]>([]);

  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [loadingRun, setLoadingRun] = useState(false);
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

  // Load run history whenever the selected job changes — this is what makes
  // a completed run revisitable without re-running the pipeline.
  useEffect(() => {
    if (selectedJobId == null) return;
    setResult(null);
    listLiveRuns(selectedJobId)
      .then(setRuns)
      .catch(() => setRuns([]));
  }, [selectedJobId]);

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
      const res = await runLiveRecommend({ job_order_id: selectedJobId });
      setResult(res);
      setRuns((prev) => [
        {
          run_id: res.run_id,
          job_order_id: selectedJobId,
          completed_at: new Date().toISOString(),
          title: res.job.title,
          company: res.job.company,
          candidates_considered: res.candidates_considered,
          candidates_passed_filter: res.candidates_passed_filter,
          candidates_reranked: res.candidates_reranked,
        },
        ...prev,
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectRun(runId: string) {
    setLoadingRun(true);
    setError(null);
    try {
      const res = await getLiveRun(runId);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load that run.");
    } finally {
      setLoadingRun(false);
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

        {!result && !loading && !loadingRun && !error && (
          <div className="flex h-48 items-center justify-center text-center text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>
            Pick a live open role and run the pipeline — reads live candidates/jobs from Mothership,
            filters via the constraint engine, then ranks via the coarse-then-fine LLM funnel.
          </div>
        )}

        {loading && (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-center text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "#d5fa54" }} />
            Extracting job requirements, filtering candidates, and ranking — this can take several minutes over the full candidate pool.
          </div>
        )}

        {!loading && loadingRun && (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-center text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "#d5fa54" }} />
            Loading saved run…
          </div>
        )}

        {result && !loading && (
          <div className="flex flex-col gap-5 lg:flex-row">
            <LiveRolePane
              job={result.job}
              coarseBrief={result.coarse_brief}
              stats={{
                candidatesConsidered: result.candidates_considered,
                candidatesIndexed: result.candidates_indexed,
                candidatesPassedFilter: result.candidates_passed_filter,
                candidatesReranked: result.candidates_reranked,
                eliminatedCount: result.eliminated.length,
              }}
              runs={runs}
              activeRunId={result.run_id}
              onSelectRun={handleSelectRun}
            />
            <LiveCandidateList ranked={result.ranked} eliminated={result.eliminated} />
          </div>
        )}
      </div>
    </div>
  );
}
