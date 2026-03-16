import { Check, Circle, Loader2 } from "lucide-react";
import type { PipelineStepState } from "../types";

interface Props {
  steps: PipelineStepState[];
}

export default function PipelineStatus({ steps }: Props) {
  return (
    <div className="flex flex-col justify-center flex-1 gap-3">
      <p className="text-xs font-medium uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.35)" }}>
        Running pipeline
      </p>
      <ol className="space-y-3.5">
        {steps.map((step) => (
          <li key={step.id} className="flex items-center gap-3">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center">
              {step.status === "done" && (
                <Check className="h-3.5 w-3.5" style={{ color: "#d5fa54" }} />
              )}
              {step.status === "active" && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "#d5fa54" }} />
              )}
              {step.status === "pending" && (
                <Circle className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.2)" }} />
              )}
            </span>
            <span
              className="text-sm transition-colors"
              style={{
                color:
                  step.status === "active"
                    ? "#ffffff"
                    : step.status === "done"
                    ? "rgba(255,255,255,0.3)"
                    : "rgba(255,255,255,0.25)",
                textDecoration: step.status === "done" ? "line-through" : "none",
              }}
            >
              {step.label}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
