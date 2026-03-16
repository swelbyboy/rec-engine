import { useState } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import type { PipelineStep, PipelineStepState, RecommendResult, ReviewAlert } from "./types";
import { recommendStream } from "./lib/api";
import JobInput from "./components/JobInput";
import PipelineStatus from "./components/PipelineStatus";
import ResultsPanel from "./components/ResultsPanel";
import JobDetailsPanel from "./components/JobDetailsPanel";

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
  const [appState, setAppState] = useState<AppState>("idle");
  const [steps, setSteps] = useState<PipelineStepState[]>(STEPS);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewAlerts, setReviewAlerts] = useState<ReviewAlert[]>([]);

  async function handleSubmit(jdText: string) {
    setAppState("loading");
    setError(null);
    setResult(null);
    setReviewAlerts([]);
    setSteps(STEPS.map((s) => ({ ...s, status: "pending" })));

    try {
      for await (const event of recommendStream({ jd_text: jdText })) {
        if (event.type === "step") {
          setSteps((prev) => transitionSteps(prev, event.step));
        } else if (event.type === "meta") {
          // Show ranked list immediately — explanations will fill in as they stream
          setResult({
            job_id: "",
            job_title: event.job_title,
            job_details: event.job_details,
            ranked_candidates: event.ranked_candidates,
            eliminated_candidates: event.eliminated_candidates,
            review_alerts: event.review_alerts,
            retrieved_candidates: event.retrieved_candidates,
            weights_used: event.weights_used,
            profile_used: event.profile_used,
          });
          setReviewAlerts(event.review_alerts ?? []);
        } else if (event.type === "explanation") {
          // Slot the explanation into the correct rank
          setResult((prev) => {
            if (!prev) return prev;
            const updated = prev.ranked_candidates.map((c) =>
              c.rank === event.rank ? { ...c, explanation: event.explanation } : c
            );
            return { ...prev, ranked_candidates: updated };
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
    setReviewAlerts([]);
    setError(null);
    setSteps(STEPS.map((s) => ({ ...s, status: "pending" })));
  }

  const isLoading = appState === "loading";
  const hasResult = result !== null;

  return (
    <div className="flex flex-col h-full">
      <header className="flex-none px-8 py-5 border-b" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="mx-auto max-w-screen-xl flex items-baseline gap-3">
          <span className="text-sm font-semibold tracking-tight text-white">Recruiter</span>
          <span className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            Candidate Recommendation Engine
          </span>
        </div>
      </header>

      <main className="flex-1 overflow-hidden mx-auto w-full max-w-screen-xl px-8 py-6 flex gap-5">
        {/* Left column */}
        <div className="w-1/2 flex flex-col gap-3 min-h-0">
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
              className="flex-none rounded-xl border px-4 py-3"
              style={{ background: "rgba(217,119,6,0.1)", borderColor: "rgba(217,119,6,0.25)" }}
            >
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                <p className="text-xs font-semibold text-amber-400">
                  {reviewAlerts.length} constraint{reviewAlerts.length > 1 ? "s" : ""} need verification
                </p>
              </div>
              <ul className="space-y-1">
                {reviewAlerts.map((a, i) => (
                  <li key={i} className="text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>
                    <span className="font-medium text-amber-400/80">{a.candidate_name}</span>
                    {" — "}
                    {a.constraint}: {a.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="w-1/2 flex flex-col min-h-0">
          <div
            className="flex-1 flex flex-col rounded-xl border min-h-0 overflow-hidden"
            style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
          >
            <ResultsPanel result={result} isLoading={isLoading && !hasResult} />
          </div>
        </div>
      </main>
    </div>
  );
}
