import { useEffect, useState } from "react";
import { AlertTriangle, Github, RotateCcw } from "lucide-react";
import type {
  CandidateRow,
  FeedbackRecord,
  PipelineStep,
  PipelineStepState,
  RankedCandidate,
  RecommendResult,
  ReviewAlert,
  ShortlistEntry,
} from "./types";
import { featureVectorToArray, listCandidates, recommendStream, submitFeedback } from "./lib/api";
import JobInput from "./components/JobInput";
import PipelineStatus from "./components/PipelineStatus";
import ResultsPanel from "./components/ResultsPanel";
import JobDetailsPanel from "./components/JobDetailsPanel";
import CandidatesTable from "./components/CandidatesTable";
import HirerPanel from "./components/HirerPanel";
import ModelTrainingPanel from "./components/ModelTrainingPanel";
import HowItWorksPanel from "./components/HowItWorksPanel";

type Tab = "recruiter" | "hirer" | "candidates" | "how-it-works";

const STEPS: PipelineStepState[] = [
  { id: "parsing", label: "Parsing job description", status: "pending" },
  { id: "retrieving", label: "Retrieving top candidates", status: "pending" },
  { id: "constraints", label: "Running constraint engine", status: "pending" },
  { id: "scoring", label: "Scoring and ranking", status: "pending" },
  { id: "explaining", label: "Generating explanations", status: "pending" },
];

const STEP_ORDER: PipelineStep[] = ["parsing", "retrieving", "constraints", "scoring", "explaining"];

type AppState = "idle" | "loading" | "done";

function transitionSteps(prev: PipelineStepState[], active: PipelineStep): PipelineStepState[] {
  const activeIdx = STEP_ORDER.indexOf(active);
  return prev.map((s, i) => ({
    ...s,
    status: i < activeIdx ? "done" : i === activeIdx ? "active" : "pending",
  }));
}

export default function App() {
  const [tab, setTab] = useState<Tab>("recruiter");
  const [appState, setAppState] = useState<AppState>("idle");
  const [steps, setSteps] = useState<PipelineStepState[]>(STEPS);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewAlerts, setReviewAlerts] = useState<ReviewAlert[]>([]);

  // Shortlist state (recruiter curation)
  const [shortlist, setShortlist] = useState<{ entries: ShortlistEntry[] } | null>(null);
  const [hirerShortlist, setHirerShortlist] = useState<ShortlistEntry[] | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string>("");

  // Candidate pool for hirer view enrichment
  const [candidatePool, setCandidatePool] = useState<Map<string, CandidateRow>>(new Map());

  // Fetch candidate pool once on mount
  useEffect(() => {
    listCandidates()
      .then((rows) => {
        const map = new Map<string, CandidateRow>();
        rows.forEach((r) => map.set(r.id, r));
        setCandidatePool(map);
      })
      .catch(() => {/* non-fatal */});
  }, []);

  async function handleSubmit(jdText: string) {
    setAppState("loading");
    setError(null);
    setResult(null);
    setShortlist(null);
    setHirerShortlist(null);
    setCurrentJobId("");
    setReviewAlerts([]);
    setSteps(STEPS.map((s) => ({ ...s, status: "pending" })));

    try {
      for await (const event of recommendStream({ jd_text: jdText, profile: "gbt" })) {
        if (event.type === "step") {
          setSteps((prev) => transitionSteps(prev, event.step));
        } else if (event.type === "meta") {
          setCurrentJobId(event.job_id);
          const newResult: RecommendResult = {
            job_id: event.job_id,
            job_title: event.job_title,
            job_details: event.job_details,
            ranked_candidates: event.ranked_candidates,
            eliminated_candidates: event.eliminated_candidates,
            review_alerts: event.review_alerts,
            retrieved_candidates: event.retrieved_candidates,
            weights_used: event.weights_used,
            profile_used: event.profile_used,
          };
          setResult(newResult);
          setReviewAlerts(event.review_alerts ?? []);
          // Initialise shortlist from ranked candidates
          setShortlist({
            entries: event.ranked_candidates.map((c: RankedCandidate) => ({
              candidate: c,
              note: "",
              removed: false,
              manuallyAdded: false,
            })),
          });
        } else if (event.type === "explanation") {
          setResult((prev) => {
            if (!prev) return prev;
            const updated = prev.ranked_candidates.map((c) =>
              c.rank === event.rank ? { ...c, explanation: event.explanation } : c
            );
            return { ...prev, ranked_candidates: updated };
          });
          // Also update shortlist entry explanations
          setShortlist((prev) => {
            if (!prev) return prev;
            return {
              entries: prev.entries.map((e) =>
                e.candidate.rank === event.rank
                  ? { ...e, candidate: { ...e.candidate, explanation: event.explanation } }
                  : e
              ),
            };
          });
        } else if (event.type === "done") {
          setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
          setAppState("done");
        } else if (event.type === "error") {
          setError(event.message);
          setAppState("idle");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
      setAppState("idle");
    }
  }

  function handleReset() {
    setAppState("idle");
    setResult(null);
    setShortlist(null);
    setHirerShortlist(null);
    setReviewAlerts([]);
    setError(null);
    setSteps(STEPS.map((s) => ({ ...s, status: "pending" })));
  }

  // Shortlist mutation handlers
  function handleReorder(fromIdx: number, toIdx: number) {
    setShortlist((prev) => {
      if (!prev) return prev;
      const entries = [...prev.entries];
      const [moved] = entries.splice(fromIdx, 1);
      entries.splice(toIdx, 0, moved);
      return { entries };
    });
  }

  function handleRemove(candidateId: string, removed: boolean) {
    setShortlist((prev) => {
      if (!prev) return prev;
      return {
        entries: prev.entries.map((e) =>
          e.candidate.candidate_id === candidateId ? { ...e, removed } : e
        ),
      };
    });
  }

  function handleNoteChange(candidateId: string, note: string) {
    setShortlist((prev) => {
      if (!prev) return prev;
      return {
        entries: prev.entries.map((e) =>
          e.candidate.candidate_id === candidateId ? { ...e, note } : e
        ),
      };
    });
  }

  function handleAddCandidate(candidate: RankedCandidate) {
    setShortlist((prev) => {
      if (!prev) return prev;
      // Don't add duplicates
      if (prev.entries.some((e) => e.candidate.candidate_id === candidate.candidate_id)) {
        return {
          entries: prev.entries.map((e) =>
            e.candidate.candidate_id === candidate.candidate_id ? { ...e, removed: false } : e
          ),
        };
      }
      return {
        entries: [...prev.entries, { candidate, note: "", removed: false, manuallyAdded: true }],
      };
    });
  }

  function handleSendToHirer() {
    if (!shortlist) return;

    // Build feedback records from non-manually-added entries
    const feedbackRecords: FeedbackRecord[] = shortlist.entries
      .filter((e) => !e.manuallyAdded)
      .map((e) => ({
        candidate_id: e.candidate.candidate_id,
        job_id: currentJobId,
        features: featureVectorToArray(e.candidate.feature_vector),
        outcome: e.removed ? 0 : 1,
        source: "recruiter" as const,
      }));

    // Fire-and-forget feedback submission
    if (feedbackRecords.length > 0) {
      submitFeedback(feedbackRecords).catch(() => {/* non-fatal */});
    }

    // Pass kept entries directly to hirer view
    const kept = shortlist.entries.filter((e) => !e.removed);
    setHirerShortlist(kept);
    setTab("hirer");
  }

  const isLoading = appState === "loading";
  const hasResult = result !== null;

  return (
    <div className="flex flex-col h-full">
      <header className="flex-none px-8 border-b" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="mx-auto max-w-screen-xl flex items-center justify-between h-14">
          {/* Left: wordmark + tabs */}
          <div className="flex items-center gap-6">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-semibold tracking-tight text-white">Recruiter</span>
            </div>
            <nav className="flex items-center gap-1">
              {(["recruiter", "hirer", "candidates", "how-it-works"] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
                  style={{
                    background: tab === t ? "rgba(255,255,255,0.08)" : "transparent",
                    color: tab === t ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.35)",
                  }}
                >
                  {t === "recruiter" ? "Recruiter" : t === "hirer" ? "Hirer" : t === "candidates" ? "Candidates" : "How it works"}
                </button>
              ))}
            </nav>
          </div>
          {/* Right: GitHub */}
          <a
            href="https://github.com/swelbyboy/rec-engine"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs transition-colors"
            style={{ color: "rgba(255,255,255,0.35)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.7)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.35)")}
          >
            <Github className="h-4 w-4" />
          </a>
        </div>
      </header>

      {/* Candidates tab */}
      {tab === "candidates" && (
        <main className="flex-1 overflow-auto mx-auto w-full max-w-screen-xl px-8 py-6">
          <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Candidate pool
          </p>
          <CandidatesTable />
        </main>
      )}

      {/* How it works tab */}
      {tab === "how-it-works" && (
        <main className="flex-1 overflow-auto mx-auto w-full max-w-screen-xl px-8 py-6">
          <p className="mb-6 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            How it works
          </p>
          <HowItWorksPanel />
        </main>
      )}

      {/* Hirer tab */}
      {tab === "hirer" && (
        <main className="flex-1 overflow-hidden mx-auto w-full max-w-screen-xl px-4 md:px-8 py-6 flex flex-col md:flex-row gap-5">
          {/* Left column — placeholder matching recruiter left column width */}
          <div className="hidden md:flex w-full md:w-1/2 flex-col min-h-0">
            <div
              className="flex-1 flex flex-col rounded-xl border p-6 min-h-0 items-center justify-center gap-3 text-center"
              style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
            >
              <p className="text-xs font-medium" style={{ color: "rgba(255,255,255,0.25)" }}>
                Shortlist sent by recruiter
              </p>
            </div>
          </div>

          {/* Right column — candidate list */}
          <div className="w-full md:w-1/2 flex flex-col min-h-0">
            <div
              className="flex-1 flex flex-col rounded-xl border min-h-0 overflow-hidden"
              style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
            >
              <HirerPanel shortlist={hirerShortlist} />
            </div>
          </div>
        </main>
      )}

      {tab === "recruiter" && (
        <main className="flex-1 overflow-auto md:overflow-hidden mx-auto w-full max-w-screen-xl px-4 md:px-8 py-6 flex flex-col md:flex-row gap-5">
          {/* Left column */}
          <div className="w-full md:w-1/2 flex flex-col gap-3 min-h-0">
            <div
              className="flex-1 flex flex-col rounded-xl border p-6 min-h-0"
              style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
            >
              {isLoading ? (
                <PipelineStatus steps={steps} />
              ) : appState === "done" && result?.job_details ? (
                <div className="flex flex-col h-full min-h-0 gap-4">
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                      Evaluation complete
                    </p>
                    <button
                      onClick={handleReset}
                      className="flex items-center gap-1.5 text-xs transition-colors"
                      style={{ color: "rgba(255,255,255,0.35)" }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = "#d5fa54")}
                      onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.35)")}
                    >
                      <RotateCcw className="h-3 w-3" />
                      New search
                    </button>
                  </div>
                  <div className="flex-1 min-h-0 overflow-y-auto">
                    <JobDetailsPanel title={result.job_title} details={result.job_details} />
                  </div>
                </div>
              ) : (
                <JobInput onSubmit={handleSubmit} isLoading={isLoading} />
              )}
            </div>

            {error && (
              <div
                className="flex-none rounded-xl border px-4 py-3"
                style={{ background: "rgba(220,38,38,0.1)", borderColor: "rgba(220,38,38,0.25)" }}
              >
                <p className="text-sm font-medium text-red-400">Error</p>
                <p className="mt-0.5 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{error}</p>
              </div>
            )}

            {reviewAlerts.length > 0 && (
              <div
                className="flex-none rounded-xl border px-3 py-2.5 flex items-center gap-2"
                style={{ background: "rgba(217,119,6,0.08)", borderColor: "rgba(217,119,6,0.2)" }}
              >
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                <p className="text-xs text-amber-400">
                  <span className="font-semibold">{reviewAlerts.length}</span> constraint{reviewAlerts.length > 1 ? "s" : ""} flagged for verification — see candidate cards for details
                </p>
              </div>
            )}

            {appState === "done" && (
              <ModelTrainingPanel />
            )}
          </div>

          {/* Right column */}
          <div className="w-full md:w-1/2 flex flex-col min-h-0">
            <div
              className="flex-1 flex flex-col rounded-xl border min-h-0 overflow-hidden"
              style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
            >
              <ResultsPanel
                result={result}
                isLoading={isLoading && !hasResult}
                shortlist={shortlist}
                onReorder={handleReorder}
                onRemove={handleRemove}
                onNoteChange={handleNoteChange}
                onAddCandidate={handleAddCandidate}
                onSendToHirer={handleSendToHirer}
                candidatePool={candidatePool}
              />
            </div>
          </div>
        </main>
      )}
    </div>
  );
}
