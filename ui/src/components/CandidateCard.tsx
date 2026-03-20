import { useState } from "react";
import { ChevronDown, ChevronUp, ArrowUp, ArrowDown, X } from "lucide-react";
import type { CandidateRequirement, RankedCandidate } from "../types";

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

function formatRequirementValue(req: CandidateRequirement): string {
  const val = req.value;
  if (val === null || val === undefined) return "";
  if (req.currency) return `${req.currency} ${Number(val).toLocaleString()}`;
  if (typeof val === "boolean") return val ? "yes" : "no";
  if (req.canonical_key === "notice_period_weeks") return `${val} weeks`;
  return String(val);
}

function parseExplanation(text: string): string[] {
  const byBlankLine = text.split(/\n\s*\n/).map((p) => p.replace(/\n/g, " ").trim()).filter(Boolean);
  if (byBlankLine.length >= 2) return byBlankLine;
  const sentences = text.match(/[^.!?]+[.!?]+/g) ?? [text];
  const mid = Math.ceil(sentences.length / 2);
  return [sentences.slice(0, mid).join(" "), sentences.slice(mid).join(" ")].filter(Boolean);
}

interface AugmentProps {
  rank: number;
  totalActive: number;
  removed: boolean;
  note: string;
  isOverride?: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onUndo: () => void;
  onNoteChange: (note: string) => void;
}

interface Props {
  candidate: RankedCandidate;
  augment?: AugmentProps;
}

export default function CandidateCard({ candidate, augment }: Props) {
  const [expanded, setExpanded] = useState(false);
  const pct = Math.round(candidate.score * 100);
  const accent = scoreAccent(candidate.score);
  const paragraphs = parseExplanation(candidate.explanation);

  const features = (Object.entries(candidate.feature_vector) as [string, number][]).filter(
    ([key]) => !SKIP_FEATURE_KEYS.has(key) && FEATURE_LABELS[key]
  );

  const isRemoved = augment?.removed ?? false;

  return (
    <div
      className="rounded-xl border overflow-hidden transition-opacity"
      style={{
        background: "#0f1012",
        borderColor: candidate.flagged_for_review ? "rgba(217,119,6,0.35)" : "rgba(255,255,255,0.07)",
        opacity: isRemoved ? 0.45 : 1,
      }}
    >
      {/* Collapsed row */}
      <div className="flex items-start gap-2 px-4 py-3.5">
        {/* Reorder arrows (augment mode only) */}
        {augment && !isRemoved && (
          <div className="flex flex-col gap-0.5 mt-1 shrink-0">
            <button
              onClick={augment.onMoveUp}
              disabled={augment.rank <= 1}
              className="p-0.5 rounded transition-colors disabled:opacity-20"
              style={{ color: "rgba(255,255,255,0.4)" }}
              onMouseEnter={(e) => { if (!augment.rank || augment.rank > 1) (e.currentTarget as HTMLElement).style.color = "#d5fa54"; }}
              onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.4)"}
              title="Move up"
            >
              <ArrowUp className="h-3 w-3" />
            </button>
            <button
              onClick={augment.onMoveDown}
              disabled={augment.rank >= augment.totalActive}
              className="p-0.5 rounded transition-colors disabled:opacity-20"
              style={{ color: "rgba(255,255,255,0.4)" }}
              onMouseEnter={(e) => { if (augment.rank < augment.totalActive) (e.currentTarget as HTMLElement).style.color = "#d5fa54"; }}
              onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.4)"}
              title="Move down"
            >
              <ArrowDown className="h-3 w-3" />
            </button>
          </div>
        )}

        {/* Rank badge */}
        <span
          className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
          style={isRemoved ? { background: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.3)", border: "1px solid rgba(255,255,255,0.1)" } : scoreBadgeStyle(candidate.score)}
        >
          {augment ? augment.rank : candidate.rank}
        </span>

        {/* Clickable name + snippet */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 min-w-0 text-left"
        >
          <div className="flex items-center gap-2">
            <span
              className="text-sm font-medium"
              style={{
                color: isRemoved ? "rgba(255,255,255,0.35)" : "white",
                textDecoration: isRemoved ? "line-through" : "none",
              }}
            >
              {candidate.name}
            </span>
            {candidate.flagged_for_review && !isRemoved && (
              <span
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={{ background: "rgba(217,119,6,0.15)", color: "#f59e0b" }}
              >
                Review needed
              </span>
            )}
            {augment?.isOverride && !isRemoved && (
              <span
                className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={{ background: "rgba(255,102,196,0.12)", color: "#ff66c4", border: "1px solid rgba(255,102,196,0.2)" }}
              >
                Override
              </span>
            )}
          </div>
          {!isRemoved && (
            candidate.explanation ? (
              <p className="mt-1 text-xs leading-relaxed line-clamp-2" style={{ color: "rgba(255,255,255,0.4)" }}>
                {paragraphs[0]}
              </p>
            ) : (
              <div className="mt-1.5 space-y-1.5">
                <div className="h-2 w-3/4 rounded animate-pulse" style={{ background: "rgba(255,255,255,0.08)" }} />
                <div className="h-2 w-1/2 rounded animate-pulse" style={{ background: "rgba(255,255,255,0.05)" }} />
              </div>
            )
          )}
        </button>

        {/* Match score (hidden when removed) */}
        {!isRemoved && (
          <div className="shrink-0 flex flex-col items-end gap-1.5 ml-2">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>Rank score</span>
              <span className="text-xs font-semibold" style={{ color: accent }}>{pct}%</span>
            </div>
            <div className="w-20 h-1 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
              <div className="h-full rounded-full" style={{ width: `${pct}%`, background: accent }} />
            </div>
          </div>
        )}

        {/* Augmentation controls */}
        {augment && (
          <div className="shrink-0 flex items-center gap-1 ml-2">
            {isRemoved ? (
              <button
                onClick={augment.onUndo}
                className="text-xs px-2 py-0.5 rounded transition-colors"
                style={{ color: "#5170ff", border: "1px solid rgba(81,112,255,0.3)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(81,112,255,0.1)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                Undo
              </button>
            ) : (
              <button
                onClick={augment.onRemove}
                className="p-1 rounded transition-colors"
                style={{ color: "rgba(255,255,255,0.3)" }}
                onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "#ff66c4"}
                onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.3)"}
                title="Remove from shortlist"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Expand toggle */}
        <button onClick={() => setExpanded((v) => !v)} className="shrink-0 mt-0.5">
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.3)" }} />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.3)" }} />
          )}
        </button>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t px-4 pb-5 pt-4 space-y-5" style={{ borderColor: "rgba(255,255,255,0.07)" }}>
          {/* Explanation paragraphs */}
          <div>
            <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
              Assessment
            </p>
            {candidate.explanation ? (
              <div className="space-y-3">
                {paragraphs.map((para, i) => (
                  <p key={i} className="text-sm leading-relaxed" style={{ color: "rgba(255,255,255,0.7)" }}>
                    {para}
                  </p>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-2.5 rounded animate-pulse" style={{ background: "rgba(255,255,255,0.07)", width: i === 3 ? "60%" : "100%" }} />
                ))}
              </div>
            )}
          </div>

          {/* Recruiter note (augment mode only) */}
          {augment && (
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Recruiter note
              </p>
              <textarea
                value={augment.note}
                onChange={(e) => augment.onNoteChange(e.target.value)}
                placeholder="Add a note for the hirer..."
                rows={2}
                className="w-full resize-none rounded-lg px-3 py-2 text-xs outline-none"
                style={{
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  color: "rgba(255,255,255,0.7)",
                }}
                onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(213,250,84,0.4)")}
                onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
              />
            </div>
          )}

          {/* Candidate requirements not addressed by JD */}
          {candidate.candidate_requirements && candidate.candidate_requirements.length > 0 && (
            <div>
              <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                Candidate requirements
              </p>
              <div className="flex flex-wrap gap-2">
                {candidate.candidate_requirements.map((req, i) => {
                  const valStr = formatRequirementValue(req);
                  return (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs"
                      style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}
                    >
                      <span style={{ color: "rgba(255,255,255,0.35)" }}>{req.description.split(":")[0].trim()}</span>
                      {valStr && <span className="font-medium text-white">{valStr}</span>}
                    </span>
                  );
                })}
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
