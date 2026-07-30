import { ChevronDown } from "lucide-react";
import type { LiveCoarseBrief, LiveRunSummary } from "../types";

const FLEX_STYLE: Record<string, { fg: string; label: string }> = {
  rigid: { fg: "rgba(255,255,255,0.4)", label: "Rigid" },
  some_flex: { fg: "#eab86b", label: "Some flex" },
  likely_flexible: { fg: "#d5fa54", label: "Likely flexible" },
};

interface LiveRolePaneProps {
  job: { id: string; title: string; company: string };
  coarseBrief: LiveCoarseBrief;
  stats: {
    candidatesConsidered: number;
    candidatesIndexed: number;
    candidatesPassedFilter: number;
    candidatesReranked: number;
    eliminatedCount: number;
  };
  runs: LiveRunSummary[];
  activeRunId: string | null;
  onSelectRun: (runId: string) => void;
}

export default function LiveRolePane({ job, coarseBrief, stats, runs, activeRunId, onSelectRun }: LiveRolePaneProps) {
  return (
    <div
      className="flex w-full flex-none flex-col gap-5 lg:w-[340px] lg:border-r lg:pr-5"
      style={{ borderColor: "rgba(255,255,255,0.08)" }}
    >
      {runs.length > 1 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Run history ({runs.length})
          </p>
          <div className="relative">
            <select
              value={activeRunId ?? ""}
              onChange={(e) => onSelectRun(e.target.value)}
              className="w-full appearance-none rounded-lg border pl-3 pr-8 py-2 text-xs font-medium outline-none"
              style={{ background: "#0b0c0d", borderColor: "rgba(255,255,255,0.12)", color: "white" }}
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {new Date(r.completed_at).toLocaleString()} — {r.candidates_reranked} ranked
                </option>
              ))}
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
              style={{ color: "rgba(255,255,255,0.4)" }}
            />
          </div>
        </div>
      )}

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          {job.company}
        </p>
        <h2 className="text-lg font-semibold text-white">{job.title}</h2>
        <p className="mt-2 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{coarseBrief.summary}</p>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesConsidered} of {stats.candidatesIndexed} scanned
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesPassedFilter} passed filter
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.eliminatedCount} eliminated
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesReranked} reranked
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          UK-based required: {coarseBrief.requires_uk_based}
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          Sponsors visa: {coarseBrief.offers_visa_sponsorship}
        </span>
      </div>

      {coarseBrief.flexibility_notes.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)" }}>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Constraint flexibility judgment
          </p>
          <div className="flex flex-col gap-1.5">
            {coarseBrief.flexibility_notes.map((n, i) => (
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
    </div>
  );
}
