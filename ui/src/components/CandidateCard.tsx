import { useState } from "react";
import { ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";
import type { RankedCandidate } from "../types";

const FEATURE_LABELS: Record<string, string> = {
  required_skills_overlap: "Required skills",
  preferred_skills_overlap: "Preferred skills",
  industry_preferred_match: "Industry match",
  experience_delta: "Experience",
  seniority_match: "Seniority",
  career_trajectory_score: "Career trajectory",
  interview_score: "Interview",
  culture_fit_score: "Culture fit",
  management_match: "Management",
  soft_constraint_score: "Constraint compliance",
};

function scoreAccent(score: number): string {
  if (score >= 0.75) return "#d5fa54";  // lime
  if (score >= 0.5) return "#5170ff";   // blue
  return "#ff66c4";                      // magenta
}

function scoreBadgeStyle(score: number) {
  const color = scoreAccent(score);
  return {
    background: `${color}18`,
    color: color,
    border: `1px solid ${color}30`,
  };
}

interface Props {
  candidate: RankedCandidate;
}

export default function CandidateCard({ candidate }: Props) {
  const [expanded, setExpanded] = useState(false);
  const pct = Math.round(candidate.score * 100);
  const accent = scoreAccent(candidate.score);
  const features = Object.entries(candidate.feature_vector) as [string, number][];

  return (
    <div
      className="rounded-xl border overflow-hidden transition-colors"
      style={{
        background: "#0f1012",
        borderColor: candidate.flagged_for_review
          ? "rgba(217,119,6,0.35)"
          : "rgba(255,255,255,0.07)",
      }}
    >
      {/* Collapsed row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {/* Rank */}
        <span
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
          style={scoreBadgeStyle(candidate.score)}
        >
          {candidate.rank}
        </span>

        {/* Name */}
        <span className="flex-1 text-sm font-medium text-white truncate">
          {candidate.name}
        </span>

        {/* Flag */}
        {candidate.flagged_for_review && (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
        )}

        {/* Score bar */}
        <div className="hidden sm:flex items-center gap-2 w-28 shrink-0">
          <div
            className="h-1 flex-1 overflow-hidden rounded-full"
            style={{ background: "rgba(255,255,255,0.08)" }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${pct}%`, background: accent }}
            />
          </div>
          <span className="text-xs font-medium w-8 text-right" style={{ color: accent }}>
            {pct}%
          </span>
        </div>

        {/* Snippet */}
        <span
          className="hidden lg:block w-44 shrink-0 truncate text-xs"
          style={{ color: "rgba(255,255,255,0.35)" }}
        >
          {candidate.explanation.slice(0, 70)}…
        </span>

        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5 shrink-0" style={{ color: "rgba(255,255,255,0.3)" }} />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" style={{ color: "rgba(255,255,255,0.3)" }} />
        )}
      </button>

      {/* Expanded body */}
      {expanded && (
        <div
          className="px-4 pb-5 pt-4 space-y-5 border-t"
          style={{ borderColor: "rgba(255,255,255,0.07)" }}
        >
          {/* Explanation */}
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
              Explanation
            </p>
            <p className="text-sm leading-relaxed" style={{ color: "rgba(255,255,255,0.7)" }}>
              {candidate.explanation}
            </p>
          </div>

          {/* Feature vector */}
          <div>
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
              Feature scores
            </p>
            <div className="space-y-2">
              {features.map(([key, val]) => {
                const v = Math.max(0, Math.min(100, Math.round(val * 100)));
                const a = scoreAccent(val);
                return (
                  <div key={key} className="flex items-center gap-3">
                    <span className="w-40 shrink-0 text-xs" style={{ color: "rgba(255,255,255,0.45)" }}>
                      {FEATURE_LABELS[key] ?? key}
                    </span>
                    <div
                      className="h-1 flex-1 overflow-hidden rounded-full"
                      style={{ background: "rgba(255,255,255,0.07)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${v}%`, background: a }}
                      />
                    </div>
                    <span className="w-7 text-right text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
                      {v}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Constraint checks */}
          {candidate.constraint_matches.length > 0 && (
            <div>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Constraint checks
              </p>
              <div
                className="overflow-hidden rounded-lg border"
                style={{ borderColor: "rgba(255,255,255,0.08)" }}
              >
                <table className="w-full text-xs">
                  <thead>
                    <tr style={{ background: "rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
                      <th className="px-3 py-2 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Type</th>
                      <th className="px-3 py-2 text-center font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>OK?</th>
                      <th className="px-3 py-2 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidate.constraint_matches.map((m, i) => (
                      <tr
                        key={i}
                        className="border-t"
                        style={{
                          borderColor: "rgba(255,255,255,0.05)",
                          background: m.flagged ? "rgba(217,119,6,0.07)" : "transparent",
                        }}
                      >
                        <td className="px-3 py-2 capitalize" style={{ color: "rgba(255,255,255,0.6)" }}>
                          {m.match_type.replace(/_/g, " ")}
                        </td>
                        <td className="px-3 py-2 text-center font-semibold">
                          {m.compatible ? (
                            <span style={{ color: "#d5fa54" }}>✓</span>
                          ) : (
                            <span style={{ color: "#ff66c4" }}>✗</span>
                          )}
                        </td>
                        <td className="px-3 py-2" style={{ color: "rgba(255,255,255,0.5)" }}>
                          {m.flagged && (
                            <AlertTriangle className="mr-1 inline h-3 w-3 text-amber-400" />
                          )}
                          {m.reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
