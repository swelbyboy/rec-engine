import { useState } from "react";
import { Users, ChevronDown, ChevronUp, Search, AlertCircle } from "lucide-react";

// If the best candidate's required-skills overlap is below this, the pool
// has no one with the right skills for the role (e.g. sales vs tech pool).
const SKILLS_OVERLAP_THRESHOLD = 0.15;
import type { RecommendResult } from "../types";
import CandidateCard from "./CandidateCard";

interface Props {
  result: RecommendResult | null;
  isLoading: boolean;
}

export default function ResultsPanel({ result, isLoading }: Props) {
  const [eliminatedOpen, setEliminatedOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div
          className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: "rgba(213,250,84,0.3)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-full"
          style={{ background: "rgba(255,255,255,0.05)" }}
        >
          <Search className="h-5 w-5" style={{ color: "rgba(255,255,255,0.3)" }} />
        </div>
        <div>
          <p className="text-sm font-medium" style={{ color: "rgba(255,255,255,0.5)" }}>
            No results yet
          </p>
          <p className="mt-1 text-xs" style={{ color: "rgba(255,255,255,0.25)" }}>
            Enter a job description and click Find Candidates.
          </p>
        </div>
      </div>
    );
  }

  const { ranked_candidates, eliminated_candidates, job_title } = result;
  const topSkillsOverlap = ranked_candidates[0]?.feature_vector.required_skills_overlap ?? 0;
  const noStrongMatch = topSkillsOverlap < SKILLS_OVERLAP_THRESHOLD;
  const noPoolMatch = ranked_candidates.length === 0 && eliminated_candidates.length === 0;

  if (noPoolMatch) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-full"
          style={{ background: "rgba(220,38,38,0.08)" }}
        >
          <AlertCircle className="h-5 w-5 text-red-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-red-400">No candidates for this role type</p>
          <p className="mt-1 text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            The talent pool contains no candidates in this discipline.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div
        className="flex-none flex items-center gap-2 px-5 py-3.5 border-b"
        style={{ borderColor: "rgba(255,255,255,0.07)" }}
      >
        <Users className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.35)" }} />
        <span className="text-xs font-medium text-white">
          {ranked_candidates.length} ranked
        </span>
        {eliminated_candidates.length > 0 && (
          <span className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            · {eliminated_candidates.length} eliminated
          </span>
        )}
        {job_title && (
          <span className="ml-auto text-xs italic truncate" style={{ color: "rgba(255,255,255,0.25)" }}>
            {job_title}
          </span>
        )}
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 min-h-0">
        {noStrongMatch && (
          <div
            className="rounded-lg border px-4 py-3 flex gap-3 items-start"
            style={{ background: "rgba(220,38,38,0.08)", borderColor: "rgba(220,38,38,0.2)" }}
          >
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-400" />
            <div>
              <p className="text-xs font-semibold text-red-400">No strong matches in talent pool</p>
              <p className="mt-0.5 text-xs" style={{ color: "rgba(255,255,255,0.4)" }}>
                No candidates in the current pool have the required skills for this role (best required-skills overlap: {Math.round(topSkillsOverlap * 100)}%). Results below are shown for reference only.
              </p>
            </div>
          </div>
        )}
        {ranked_candidates.map((c) => (
          <CandidateCard key={c.candidate_id} candidate={c} />
        ))}

        {/* Eliminated section */}
        {eliminated_candidates.length > 0 && (
          <div className="pt-1">
            <button
              onClick={() => setEliminatedOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-xs font-medium transition-colors"
              style={{
                background: "rgba(255,255,255,0.04)",
                color: "rgba(255,255,255,0.4)",
                border: "1px solid rgba(255,255,255,0.07)",
              }}
            >
              <span>Eliminated ({eliminated_candidates.length})</span>
              {eliminatedOpen ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </button>

            {eliminatedOpen && (
              <div className="mt-2 space-y-1.5">
                {eliminated_candidates.map((ec) => (
                  <div
                    key={ec.candidate_id}
                    className="rounded-lg px-4 py-3 border"
                    style={{
                      background: "#0f1012",
                      borderColor: "rgba(255,255,255,0.06)",
                    }}
                  >
                    <p className="text-xs font-medium text-white">{ec.name}</p>
                    <p className="mt-0.5 text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
                      {ec.elimination_reason}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
