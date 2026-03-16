import { useState, useRef } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import type { PipelineStepState, RecommendResult, ReviewAlert } from "./types";
import { recommend } from "./lib/api";
import JobInput from "./components/JobInput";
import PipelineStatus from "./components/PipelineStatus";
import ResultsPanel from "./components/ResultsPanel";
import JobDetailsPanel from "./components/JobDetailsPanel";

const INITIAL_STEPS: PipelineStepState[] = [
  { id: "parsing", label: "Parsing job description", status: "pending" },
  { id: "retrieving", label: "Retrieving top candidates", status: "pending" },
  { id: "constraints", label: "Running constraint engine", status: "pending" },
  { id: "scoring", label: "Scoring and ranking", status: "pending" },
  { id: "explaining", label: "Generating explanations", status: "pending" },
];

const STEP_DELAYS = [0, 2500, 3500, 5500, 6000];

type AppState = "idle" | "loading" | "done";

export default function App() {
  const [appState, setAppState] = useState<AppState>("idle");
  const [steps, setSteps] = useState<PipelineStepState[]>(INITIAL_STEPS);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewAlerts, setReviewAlerts] = useState<ReviewAlert[]>([]);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  function clearTimers() {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  }

  function startStepAnimation() {
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "pending" as const })));
    STEP_DELAYS.forEach((delay, idx) => {
      const t = setTimeout(() => {
        setSteps((prev) =>
          prev.map((s, i) => ({
            ...s,
            status: i < idx ? "done" : i === idx ? "active" : "pending",
          }))
        );
      }, delay);
      timersRef.current.push(t);
    });
  }

  function snapAllDone() {
    clearTimers();
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "done" })));
  }

  async function handleSubmit(jdText: string) {
    clearTimers();
    setAppState("loading");
    setError(null);
    setResult(null);
    setReviewAlerts([]);
    startStepAnimation();

    try {
      const res = await recommend({ jd_text: jdText });
      snapAllDone();
      setResult(res);
      setReviewAlerts(res.review_alerts ?? []);
      setAppState("done");
    } catch (err) {
      clearTimers();
      setAppState("idle");
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    }
  }

  function handleReset() {
    setAppState("idle");
    setResult(null);
    setReviewAlerts([]);
    setError(null);
  }

  const isLoading = appState === "loading";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex-none px-8 py-5 border-b" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <div className="mx-auto max-w-screen-xl flex items-baseline gap-3">
          <span className="text-sm font-semibold tracking-tight text-white">Recruiter</span>
          <span className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            Candidate Recommendation Engine
          </span>
        </div>
      </header>

      {/* Body */}
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

          {/* Error */}
          {error && (
            <div
              className="flex-none rounded-xl border px-4 py-3"
              style={{ background: "rgba(220,38,38,0.1)", borderColor: "rgba(220,38,38,0.25)" }}
            >
              <p className="text-sm font-medium text-red-400">Error</p>
              <p className="mt-0.5 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{error}</p>
            </div>
          )}

          {/* Review alerts */}
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
            <ResultsPanel result={result} isLoading={isLoading} />
          </div>
        </div>
      </main>
    </div>
  );
}
