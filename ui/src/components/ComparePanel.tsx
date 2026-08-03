import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, Eye, EyeOff, Loader2 } from "lucide-react";
import {
  fetchLiveJobs,
  getLiveRun,
  getLlmOnlyRun,
  getMindRun,
  listLiveRuns,
  listLlmOnlyRuns,
  listMindRuns,
} from "../lib/api";
import LiveCandidateCard from "./LiveCandidateCard";
import MindCandidateCard from "./MindCandidateCard";
import CrossModelRankModal from "./CrossModelRankModal";
import LiveRolePane from "./LiveRolePane";
import type { LiveJobSummary, LiveRecommendResult, LiveRunSummary, MindRun, MindRunSummary, RankSource } from "../types";

// Runs from before the 2026-07-31 eligibility-gate change scanned the full
// unfiltered app.candidates table (~17.6k rows) in raw candidate_id order.
// New runs are gated to Mind's own eligible pool (~2-3k) and ordered by
// recency. candidates_considered is the one field every run already has that
// distinguishes them, so it's used as a heuristic rather than requiring a
// backend migration to stamp old runs retroactively.
const FULL_UNIVERSE_THRESHOLD = 5000;

function isFullUniverseRun(r: { candidates_considered: number }): boolean {
  return r.candidates_considered > FULL_UNIVERSE_THRESHOLD;
}

function RunPicker<T extends { run_id: string }>({
  runs,
  selectedRunId,
  onSelect,
  disabled,
  labelFor,
}: {
  runs: T[];
  selectedRunId: string;
  onSelect: (runId: string) => void;
  disabled?: boolean;
  labelFor: (run: T) => string;
}) {
  return (
    <div className="relative">
      <select
        value={selectedRunId}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
        className="w-full appearance-none rounded-lg border pl-2.5 pr-7 py-1.5 text-[11px] font-medium outline-none disabled:opacity-50"
        style={{ background: "#0b0c0d", borderColor: "rgba(255,255,255,0.12)", color: "white" }}
      >
        <option value="" disabled>
          Select a run ({runs.length})
        </option>
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {labelFor(r)}
          </option>
        ))}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2"
        style={{ color: "rgba(255,255,255,0.4)" }}
      />
    </div>
  );
}

function ColumnShell({
  title,
  controls,
  children,
  hidden,
  onToggleHidden,
}: {
  title: string;
  controls: ReactNode;
  children: ReactNode;
  hidden: boolean;
  onToggleHidden: () => void;
}) {
  // Collapsed to a narrow strip rather than unmounted — the column's own
  // run-picker selection, loaded result, and its contribution to
  // rankSources/jobResults up in ComparePanel all stay intact while hidden,
  // so toggling visibility back on doesn't re-fetch or lose state, and a
  // hidden column still counts toward the cross-model rank modal.
  if (hidden) {
    return (
      <div
        className="flex flex-none w-10 flex-col items-center gap-3 rounded-xl border py-3"
        style={{ borderColor: "rgba(255,255,255,0.08)", background: "#0b0c0d" }}
      >
        <button
          onClick={onToggleHidden}
          className="rounded p-1.5 hover:bg-white/5"
          title={`Show ${title}`}
        >
          <EyeOff className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.4)" }} />
        </button>
        <p
          className="text-[10px] font-semibold uppercase tracking-widest whitespace-nowrap"
          style={{ color: "rgba(255,255,255,0.3)", writingMode: "vertical-rl" }}
        >
          {title}
        </p>
      </div>
    );
  }

  return (
    <div
      className="flex flex-1 min-w-0 flex-col rounded-xl border"
      style={{ borderColor: "rgba(255,255,255,0.08)", background: "#0b0c0d" }}
    >
      <div className="flex-none flex flex-col gap-2 border-b px-4 py-3" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            {title}
          </p>
          <button onClick={onToggleHidden} className="shrink-0 rounded p-1 hover:bg-white/5" title={`Hide ${title}`}>
            <Eye className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.4)" }} />
          </button>
        </div>
        {controls}
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-2 min-h-[220px]">{children}</div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-32 items-center justify-center text-center text-xs" style={{ color: "rgba(255,255,255,0.3)" }}>
      {text}
    </div>
  );
}

// Shared by rec-engine PoC and LLM-only — both produce the exact same
// LiveRecommendResult/LiveRunSummary shape (see funnel_rerank.
// run_llm_only_pipeline's docstring), just from different pipelines behind
// different endpoints. Parameterized by title + fetch functions so a future
// 5th "LiveRecommendResult-shaped" column needs no new component, just a
// call site here.
function LiveStyleColumn({
  title,
  jobOrderId,
  listRuns,
  getRun,
  showFullUniverseWarning,
  onRankedChange,
  onCandidateClick,
  onResultChange,
  hidden,
  onToggleHidden,
}: {
  title: string;
  jobOrderId: number | null;
  listRuns: (jobOrderId: number) => Promise<LiveRunSummary[]>;
  getRun: (runId: string) => Promise<LiveRecommendResult>;
  showFullUniverseWarning?: boolean;
  onRankedChange: (label: string, source: RankSource | null) => void;
  onCandidateClick: (candidateId: string, candidateName: string) => void;
  // Reports this column's currently-loaded full result up to ComparePanel —
  // separate from onRankedChange (which only extracts the rank lookup) so
  // the job-details side panel can read job/coarse_brief/rubric_used without
  // every column needing to care about that; optional since MindColumn has
  // no equivalent (Mind's run shape carries no parsed JobDescription).
  onResultChange?: (label: string, result: LiveRecommendResult | null) => void;
  hidden: boolean;
  onToggleHidden: () => void;
}) {
  const [runs, setRuns] = useState<LiveRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [result, setResult] = useState<LiveRecommendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setResult(null);
    setSelectedRunId("");
    setError(null);
    if (jobOrderId == null) {
      setRuns([]);
      return;
    }
    listRuns(jobOrderId)
      .then((rows) => {
        setRuns(rows);
        if (rows.length > 0) setSelectedRunId(rows[0].run_id);
      })
      .catch(() => setRuns([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobOrderId]);

  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    setError(null);
    getRun(selectedRunId)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load that run."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  // Report this column's currently-loaded ranking up to ComparePanel so the
  // cross-model modal can look up any candidate's position here without a
  // separate fetch — see CrossModelRankModal.
  useEffect(() => {
    if (!result) {
      onRankedChange(title, null);
      return;
    }
    const rankByCandidateId: Record<string, number> = {};
    result.ranked.forEach((c, i) => {
      rankByCandidateId[c.candidate_id] = i + 1;
    });
    onRankedChange(title, { label: title, rankByCandidateId, total: result.ranked.length });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, title]);

  useEffect(() => {
    onResultChange?.(title, result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, title]);

  return (
    <ColumnShell
      title={title}
      hidden={hidden}
      onToggleHidden={onToggleHidden}
      controls={
        runs.length > 0 ? (
          <RunPicker
            runs={runs}
            selectedRunId={selectedRunId}
            onSelect={setSelectedRunId}
            disabled={loading}
            labelFor={(r) =>
              `${new Date(r.completed_at).toLocaleString()} — ${r.candidates_reranked} ranked` +
              (showFullUniverseWarning && isFullUniverseRun(r) ? " · Full universe, no recency" : "")
            }
          />
        ) : (
          <p className="text-[11px]" style={{ color: "rgba(255,255,255,0.3)" }}>
            No {title} runs for this role yet
          </p>
        )
      }
    >
      {error && <p className="text-xs text-red-400">{error}</p>}
      {loading && (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin" style={{ color: "#d5fa54" }} />
        </div>
      )}
      {!loading && !result && !error && <EmptyState text="Pick a run above" />}
      {!loading && result && showFullUniverseWarning && isFullUniverseRun(result) && (
        <p
          className="mb-2 rounded-md px-2.5 py-1.5 text-[10px] font-medium"
          style={{ background: "rgba(234,179,8,0.12)", color: "#eab308" }}
        >
          ⚠ Full universe, no recency — this run scanned all {result.candidates_considered.toLocaleString()}{" "}
          candidates unfiltered, before the Mind-eligibility gate + recency ordering shipped.
        </p>
      )}
      {!loading &&
        result &&
        result.ranked.map((c, i) => (
          <LiveCandidateCard key={c.candidate_id} candidate={c} rank={i + 1} onClick={onCandidateClick} />
        ))}
    </ColumnShell>
  );
}

function MindColumn({
  title,
  runs,
  defaultRunId,
  hint,
  onRankedChange,
  onCandidateClick,
  hidden,
  onToggleHidden,
}: {
  title: string;
  runs: MindRunSummary[];
  defaultRunId: string;
  hint?: string;
  onRankedChange: (label: string, source: RankSource | null) => void;
  onCandidateClick: (candidateId: string, candidateName: string) => void;
  hidden: boolean;
  onToggleHidden: () => void;
}) {
  const [selectedRunId, setSelectedRunId] = useState(defaultRunId);
  const [result, setResult] = useState<MindRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // defaultRunId changes when the role (or the Live/Fixed distinct-version
  // pick) changes — re-sync this column's selection to the new default.
  useEffect(() => {
    setSelectedRunId(defaultRunId);
    setResult(null);
    setError(null);
  }, [defaultRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    setError(null);
    getMindRun(selectedRunId)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load that run."))
      .finally(() => setLoading(false));
  }, [selectedRunId]);

  // See LiveStyleColumn — same pattern, reported up under this column's
  // own title so "Mind Live" and "Mind Fixed" show as distinct sources even
  // though they share a component.
  useEffect(() => {
    if (!result) {
      onRankedChange(title, null);
      return;
    }
    const rankByCandidateId: Record<string, number> = {};
    result.candidates.forEach((c) => {
      if (c.reranker_rank != null) rankByCandidateId[String(c.candidate_id)] = c.reranker_rank;
    });
    onRankedChange(title, { label: title, rankByCandidateId, total: result.candidates.length });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, title]);

  return (
    <ColumnShell
      title={title}
      hidden={hidden}
      onToggleHidden={onToggleHidden}
      controls={
        runs.length > 0 ? (
          <>
            <RunPicker
              runs={runs}
              selectedRunId={selectedRunId}
              onSelect={setSelectedRunId}
              disabled={loading}
              labelFor={(r) => `${new Date(r.run_started_at).toLocaleString()} — ${r.scorer_version ?? "unknown version"}`}
            />
            {hint && (
              <p className="text-[10px] leading-snug" style={{ color: "rgba(234,184,107,0.75)" }}>
                {hint}
              </p>
            )}
          </>
        ) : (
          <p className="text-[11px]" style={{ color: "rgba(255,255,255,0.3)" }}>
            No Mind runs for this role yet
          </p>
        )
      }
    >
      {error && <p className="text-xs text-red-400">{error}</p>}
      {loading && (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin" style={{ color: "#d5fa54" }} />
        </div>
      )}
      {!loading && !result && !error && <EmptyState text="Pick a run above" />}
      {!loading &&
        result &&
        result.candidates.map((c) => (
          <MindCandidateCard key={c.candidate_id} candidate={c} onClick={onCandidateClick} />
        ))}
    </ColumnShell>
  );
}

export default function ComparePanel() {
  const [jobs, setJobs] = useState<LiveJobSummary[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  // Fetched once per role and handed to both Mind columns — Live defaults to
  // the newest run; Fixed defaults to the newest run with a *different*
  // scorer_version (the point of the comparison), falling back to the same
  // run as Live (with a hint) when no second version has been persisted yet.
  const [mindRuns, setMindRuns] = useState<MindRunSummary[]>([]);

  // Cross-model rank lookup (see CrossModelRankModal) — each column reports
  // its own currently-loaded ranking up here, keyed by column label, so any
  // card's click handler can show the same candidate's position in every
  // OTHER column too without a separate fetch. Any future column just needs
  // its own onRankedChange wired the same way (LiveStyleColumn already
  // shares this path between rec-engine PoC and LLM-only).
  const [rankSources, setRankSources] = useState<Record<string, RankSource>>({});
  const [selectedCandidate, setSelectedCandidate] = useState<{ id: string; name: string } | null>(null);

  function setRankSource(label: string, source: RankSource | null) {
    setRankSources((prev) => {
      if (!source) {
        if (!(label in prev)) return prev;
        const { [label]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [label]: source };
    });
  }

  // Job-details side panel — reuses whichever LiveStyleColumn (rec-engine
  // PoC or LLM-only) currently has a run loaded, since only those two carry
  // a parsed JobDescription (required/preferred skills, coarse role brief,
  // rubric_used); Mind's run shape doesn't. rec-engine PoC preferred over
  // LLM-only when both are loaded, since it's the one with a coarse brief +
  // rubric lookup actually populated (LLM-only always has coarse_brief={}
  // and rubric_used=null — see funnel_rerank.run_llm_only_pipeline).
  const [jobResults, setJobResults] = useState<Record<string, LiveRecommendResult | null>>({});
  function setJobResult(label: string, result: LiveRecommendResult | null) {
    setJobResults((prev) => ({ ...prev, [label]: result }));
  }
  const jobPaneSource = jobResults["rec-engine PoC"] ? "rec-engine PoC" : jobResults["LLM-only"] ? "LLM-only" : null;
  const jobPaneResult = jobPaneSource ? jobResults[jobPaneSource] : null;

  // Per-column visibility — a column stays mounted when hidden (see
  // ColumnShell's collapsed-strip branch), so hiding one is purely a view
  // preference: its run selection, loaded result, and rank/job-detail
  // contributions up here are unaffected.
  const [hiddenColumns, setHiddenColumns] = useState<Record<string, boolean>>({});
  function toggleColumnHidden(label: string) {
    setHiddenColumns((prev) => ({ ...prev, [label]: !prev[label] }));
  }

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
      setMindRuns([]);
      return;
    }
    listMindRuns(selectedJobId)
      .then(setMindRuns)
      .catch(() => setMindRuns([]));
  }, [selectedJobId]);

  // Distinguish Live vs Fixed by scorer_version content, not "newest overall" —
  // that heuristic only worked while every persisted run predated the
  // restore-legacy-score-default fix (2026-07-31). Now that both families
  // coexist, "newest run" can be either one, so each column must filter to
  // its OWN family rather than just picking a different default off the same
  // unfiltered list (which is also why both dropdowns used to show identical
  // contents — mindRuns[0] is fixed-branch as often as it's live now).
  const isFixedScorerVersion = (v?: string | null) => (v ?? "").includes("legacy-score");
  const liveRuns = mindRuns.filter((r) => !isFixedScorerVersion(r.scorer_version));
  const fixedRuns = mindRuns.filter((r) => isFixedScorerVersion(r.scorer_version));
  const liveDefault = liveRuns[0] ?? mindRuns[0];
  const fixedDefault = fixedRuns[0] ?? liveDefault;
  const fixedHint =
    mindRuns.length > 0 && fixedRuns.length === 0
      ? `No fixed-branch (legacy-score) run persisted yet — showing the same "${liveDefault?.scorer_version ?? "latest"}" run as Mind Live until one exists.`
      : undefined;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Shared role selector — same job-picker data source as the Live PoC tab */}
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

      {/* Four independent columns — each has its own run-picker, one column's data
          never blocks another's from rendering (see spec: empty-column scenario). */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="flex flex-col gap-5 lg:flex-row">
          {jobPaneResult ? (
            <div className="flex-none lg:w-[300px]">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Job details <span style={{ color: "rgba(255,255,255,0.2)" }}>· from {jobPaneSource}</span>
              </p>
              <LiveRolePane
                job={jobPaneResult.job}
                coarseBrief={jobPaneResult.coarse_brief}
                rubricUsed={jobPaneResult.rubric_used}
                stats={{
                  candidatesConsidered: jobPaneResult.candidates_considered,
                  candidatesIndexed: jobPaneResult.candidates_indexed,
                  candidatesPassedFilter: jobPaneResult.candidates_passed_filter,
                  candidatesReranked: jobPaneResult.candidates_reranked,
                  eliminatedCount: jobPaneResult.eliminated.length,
                }}
              />
            </div>
          ) : (
            selectedJobId != null && (
              <div className="w-full flex-none text-xs lg:w-[300px] lg:border-r lg:pr-5" style={{ color: "rgba(255,255,255,0.3)", borderColor: "rgba(255,255,255,0.08)" }}>
                Select a rec-engine PoC or LLM-only run below to see job details here.
              </div>
            )
          )}
          <LiveStyleColumn
            title="rec-engine PoC"
            jobOrderId={selectedJobId}
            listRuns={listLiveRuns}
            getRun={getLiveRun}
            showFullUniverseWarning
            onRankedChange={setRankSource}
            onCandidateClick={(id, name) => setSelectedCandidate({ id, name })}
            onResultChange={setJobResult}
            hidden={!!hiddenColumns["rec-engine PoC"]}
            onToggleHidden={() => toggleColumnHidden("rec-engine PoC")}
          />
          <MindColumn
            title="Mind Live"
            runs={liveRuns}
            defaultRunId={liveDefault?.run_id ?? ""}
            onRankedChange={setRankSource}
            onCandidateClick={(id, name) => setSelectedCandidate({ id, name })}
            hidden={!!hiddenColumns["Mind Live"]}
            onToggleHidden={() => toggleColumnHidden("Mind Live")}
          />
          <MindColumn
            title="Mind Fixed"
            runs={fixedRuns.length > 0 ? fixedRuns : mindRuns}
            defaultRunId={fixedDefault?.run_id ?? ""}
            hint={fixedHint}
            onRankedChange={setRankSource}
            onCandidateClick={(id, name) => setSelectedCandidate({ id, name })}
            hidden={!!hiddenColumns["Mind Fixed"]}
            onToggleHidden={() => toggleColumnHidden("Mind Fixed")}
          />
          <LiveStyleColumn
            title="LLM-only"
            jobOrderId={selectedJobId}
            listRuns={listLlmOnlyRuns}
            getRun={getLlmOnlyRun}
            onRankedChange={setRankSource}
            onCandidateClick={(id, name) => setSelectedCandidate({ id, name })}
            onResultChange={setJobResult}
            hidden={!!hiddenColumns["LLM-only"]}
            onToggleHidden={() => toggleColumnHidden("LLM-only")}
          />
        </div>
      </div>

      {selectedCandidate && (
        <CrossModelRankModal
          candidateId={selectedCandidate.id}
          candidateName={selectedCandidate.name}
          sources={Object.values(rankSources)}
          onClose={() => setSelectedCandidate(null)}
        />
      )}
    </div>
  );
}
