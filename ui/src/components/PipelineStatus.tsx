import { Check, Circle, Loader2 } from "lucide-react";
import type { PipelineStep, PipelineStepState } from "../types";

const STEP_SUBTITLES: Record<PipelineStep, string> = {
  parsing: "Dynamically extracting constraints, requirements and preferences from the JD",
  retrieving: "Embedding the role and vector-matching against all candidate profiles",
  constraints: "Excluding candidates who don't meet hard requirements",
  scoring: "Scoring each candidate across 10 weighted dimensions",
  explaining: "Summarising findings for each candidate in plain English",
};

interface Props {
  steps: PipelineStepState[];
}

export default function PipelineStatus({ steps }: Props) {
  return (
    <div className="flex flex-col justify-center flex-1 gap-3">
      <p className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: "rgba(255,255,255,0.3)" }}>
        Running pipeline
      </p>
      <ol className="space-y-5">
        {steps.map((step) => (
          <li key={step.id} className="flex items-start gap-3">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center mt-0.5">
              {step.status === "done" && (
                <Check className="h-3.5 w-3.5" style={{ color: "#d5fa54" }} />
              )}
              {step.status === "active" && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "#d5fa54" }} />
              )}
              {step.status === "pending" && (
                <Circle className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.15)" }} />
              )}
            </span>
            <div>
              <p
                className="text-sm transition-colors"
                style={{
                  color:
                    step.status === "active"
                      ? "#ffffff"
                      : step.status === "done"
                      ? "rgba(255,255,255,0.3)"
                      : "rgba(255,255,255,0.2)",
                  textDecoration: step.status === "done" ? "line-through" : "none",
                }}
              >
                {step.label}
              </p>
              {step.status !== "done" && (
                <p
                  className="mt-0.5 text-xs italic"
                  style={{
                    color:
                      step.status === "active"
                        ? "rgba(255,255,255,0.45)"
                        : "rgba(255,255,255,0.15)",
                  }}
                >
                  {STEP_SUBTITLES[step.id]}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
