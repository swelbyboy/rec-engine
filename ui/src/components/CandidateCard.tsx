import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
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

// Fields in FeatureVector that are not scores
const SKIP_FEATURE_KEYS = new Set(["candidate_id"]);

function scoreAccent(score: number): string {
  if (score >= 0.75) return "#d5fa54";
  if (score >= 0.5) return "#5170ff";
  return "#ff66c4";
}

function scoreBadgeStyle(score: number) {
  const color = scoreAccent(score);
  return { background: `${color}18`, color, border: `1px solid ${color}30` };
}

function matchTypeLabel(raw: string): string {
  const map: Record<string, string> = {
    canonical_key: "Direct match",
    semantic: "Semantic match",
    no_candidate_constraint: "No candidate restriction",
    no_match: "No match found",
  };
  return map[raw] ?? raw.replace(/_/g, " ");
}

/** Split explanation into paragraphs (blank-line separated or sentence groups) */
function parseExplanation(text: string): string[] {
  const byBlankLine = text.split(/\n\s*\n/).map((p) => p.replace(/\n/g, " ").trim()).filter(Boolean);
  if (byBlankLine.length >= 2) return byBlankLine;
  // Fallback: split into ~2 sentence chunks
  const sentences = text.match(/[^.!?]+[.!?]+/g) ?? [text];
  const mid = Math.ceil(sentences.length / 2);
  return [sentences.slice(0, mid).join(" "), sentences.slice(mid).join(" ")].filter(Boolean);
}

interface Props {
  candidate: RankedCandidate;
}

export default function CandidateCard({ candidate }: Props) {
  const [expanded, setExpanded] = useState(false);
  const pct = Math.round(candidate.score * 100);
  const accent = scoreAccent(candidate.score);
  const paragraphs = parseExplanation(candidate.explanation);

  const features = (Object.entries(candidate.feature_vector) as [string, number][]).filter(
    ([key]) => !SKIP_FEATURE_KEYS.has(key) && FEATURE_LABELS[key]
  );

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        background: "#0f1012",
        borderColor: candidate.flagged_for_review ? "rgba(217,119,6,0.35)" : "rgba(255,255,255,0.07)",
      }}
    >
      {/* Collapsed row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 px-4 py-3.5 text-left"
      >
        {/* Rank badge */}
        <span
          className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
          style={scoreBadgeStyle(candidate.score)}
        >
          {candidate.rank}
        </span>

        {/* Name + snippet */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">{candidate.name}</span>
            {candidate.flagged_for_review && (
              <span
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={{ background: "rgba(217,119,6,0.15)", color: "#f59e0b" }}
              >
                Review needed
              </span>
            )}
          </div>
          {candidate.explanation && (
            <p className="mt-1 text-xs leading-relaxed line-clamp-2" style={{ color: "rgba(255,255,255,0.4)" }}>
              {paragraphs[0]}
            </p>
          )}
        </div>

        {/* Match score */}
        <div className="shrink-0 flex flex-col items-end gap-1.5 ml-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>Match</span>
            <span className="text-xs font-semibold" style={{ color: accent }}>{pct}%</span>
          </div>
          <div className="w-20 h-1 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: accent }} />
          </div>
        </div>

        {expanded ? (
          <ChevronUp className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "rgba(255,255,255,0.3)" }} />
        ) : (
          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "rgba(255,255,255,0.3)" }} />
        )}
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t px-4 pb-5 pt-4 space-y-5" style={{ borderColor: "rgba(255,255,255,0.07)" }}>
          {/* Explanation paragraphs */}
          {candidate.explanation && (
            <div>
              <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Assessment
              </p>
              <div className="space-y-3">
                {paragraphs.map((para, i) => (
                  <p key={i} className="text-sm leading-relaxed" style={{ color: "rgba(255,255,255,0.7)" }}>
                    {para}
                  </p>
                ))}
              </div>
            </div>
          )}

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
                      {FEATURE_LABELS[key]}
                    </span>
                    <div className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.07)" }}>
                      <div className="h-full rounded-full" style={{ width: `${v}%`, background: a }} />
                    </div>
                    <span className="w-7 text-right text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>{v}%</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Constraint checks */}
          {(() => {
            // Filter out uninteresting "no candidate restriction" rows — the candidate simply
            // hasn't stated a restriction, so it defaults to compatible. Only show them when
            // flagged for verification.
            const meaningful = candidate.constraint_matches.filter(
              (m) => m.match_type !== "no_candidate_constraint" || !m.compatible || m.flagged
            );
            if (meaningful.length === 0) return null;
            return (
            <div>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Constraint checks
              </p>
              <div className="overflow-hidden rounded-lg border" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
                <table className="w-full text-xs">
                  <thead>
                    <tr style={{ background: "rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
                      <th className="px-3 py-2 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Constraint</th>
                      <th className="px-3 py-2 text-center font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>OK?</th>
                      <th className="px-3 py-2 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {meaningful.map((m, i) => (
                      <tr
                        key={i}
                        className="border-t"
                        style={{
                          borderColor: "rgba(255,255,255,0.05)",
                          background: m.flagged ? "rgba(217,119,6,0.07)" : "transparent",
                        }}
                      >
                        <td className="px-3 py-2" style={{ color: "rgba(255,255,255,0.5)" }}>
                          {matchTypeLabel(m.match_type)}
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
                            <span className="mr-1.5 inline-flex items-center rounded px-1 py-0.5 text-[10px] font-medium" style={{ background: "rgba(217,119,6,0.15)", color: "#f59e0b" }}>
                              verify
                            </span>
                          )}
                          {m.reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
