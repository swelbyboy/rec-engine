import { useState } from "react";
import { Users, ChevronDown, ChevronUp, Search, AlertCircle, Send, Plus } from "lucide-react";

const SKILLS_OVERLAP_THRESHOLD = 0.15;
import type { CandidateRow, RankedCandidate, RecommendResult, ShortlistEntry } from "../types";
import CandidateCard from "./CandidateCard";

interface Props {
  result: RecommendResult | null;
  isLoading: boolean;
  shortlist: { entries: ShortlistEntry[] } | null;
  onReorder: (fromIdx: number, toIdx: number) => void;
  onRemove: (candidateId: string, removed: boolean) => void;
  onNoteChange: (candidateId: string, note: string) => void;
  onAddCandidate: (candidate: RankedCandidate) => void;
  onSendToHirer: () => void;
  candidatePool: Map<string, CandidateRow>;
}

export default function ResultsPanel({
  result,
  isLoading,
  shortlist,
  onReorder,
  onRemove,
  onNoteChange,
  onAddCandidate,
  onSendToHirer,
  candidatePool: _candidatePool,
}: Props) {
  const [eliminatedOpen, setEliminatedOpen] = useState(false);
  const [addPoolOpen, setAddPoolOpen] = useState(false);
  const [poolSearch, setPoolSearch] = useState("");

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

  // Use shortlist entries if available, else fall back to ranked_candidates
  const entries: ShortlistEntry[] | null = shortlist?.entries ?? null;
  const activeCount = entries ? entries.filter((e) => !e.removed).length : ranked_candidates.length;

  // Compute per-entry active rank (for up/down button bounds)
  let activeRank = 0;
  const entryRanks: number[] = entries
    ? entries.map((e) => {
        if (!e.removed) { activeRank++; return activeRank; }
        return 0;
      })
    : [];

  // All shortlist candidate IDs (including removed) so we don't double-add
  const allShortlistIds = new Set(entries?.map((e) => e.candidate.candidate_id) ?? []);
  // Pool candidates not currently active in shortlist (for add-from-pool)
  const activeIds = new Set(entries?.filter((e) => !e.removed).map((e) => e.candidate.candidate_id) ?? []);
  // Combine ranked + eliminated as pool candidates
  const allPipelineCandidates: RankedCandidate[] = [
    ...ranked_candidates,
    // Build pseudo-RankedCandidate from eliminated (no feature_vector, so we skip them)
  ];
  const poolCandidates = allPipelineCandidates.filter((c) => !activeIds.has(c.candidate_id));
  const filteredPool = poolSearch.trim()
    ? poolCandidates.filter((c) => c.name.toLowerCase().includes(poolSearch.toLowerCase()))
    : poolCandidates;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div
        className="flex-none flex items-center gap-2 px-5 py-3.5 border-b"
        style={{ borderColor: "rgba(255,255,255,0.07)" }}
      >
        <Users className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.35)" }} />
        <span className="text-xs font-medium text-white">
          {activeCount} ranked
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
        {/* Send to Hirer */}
        {entries && (
          <button
            onClick={onSendToHirer}
            className="ml-2 flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors shrink-0"
            style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54", border: "1px solid rgba(213,250,84,0.2)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(213,250,84,0.18)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(213,250,84,0.1)")}
          >
            <Send className="h-3 w-3" />
            Send to Hirer
          </button>
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

        {/* Render shortlist entries if available */}
        {entries
          ? entries.map((entry, idx) => {
              const ar = entryRanks[idx];
              return (
                <CandidateCard
                  key={entry.candidate.candidate_id}
                  candidate={entry.candidate}
                  augment={{
                    rank: ar,
                    totalActive: activeCount,
                    removed: entry.removed,
                    note: entry.note,
                    isOverride: entry.manuallyAdded,
                    onMoveUp: () => {
                      if (idx > 0) onReorder(idx, idx - 1);
                    },
                    onMoveDown: () => {
                      if (idx < entries.length - 1) onReorder(idx, idx + 1);
                    },
                    onRemove: () => onRemove(entry.candidate.candidate_id, true),
                    onUndo: () => onRemove(entry.candidate.candidate_id, false),
                    onNoteChange: (note) => onNoteChange(entry.candidate.candidate_id, note),
                  }}
                />
              );
            })
          : ranked_candidates.map((c) => (
              <CandidateCard key={c.candidate_id} candidate={c} />
            ))}

        {/* Add from pool */}
        {entries && poolCandidates.length > 0 && (
          <div className="pt-1">
            <button
              onClick={() => setAddPoolOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-xs font-medium transition-colors"
              style={{
                background: "rgba(255,255,255,0.03)",
                color: "rgba(255,255,255,0.35)",
                border: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              <span className="flex items-center gap-1.5">
                <Plus className="h-3.5 w-3.5" />
                Add from pipeline ({poolCandidates.length})
              </span>
              {addPoolOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>

            {addPoolOpen && (
              <div className="mt-2 space-y-1.5">
                <input
                  type="text"
                  value={poolSearch}
                  onChange={(e) => setPoolSearch(e.target.value)}
                  placeholder="Search by name..."
                  className="w-full rounded-lg px-3 py-1.5 text-xs outline-none"
                  style={{
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    color: "rgba(255,255,255,0.7)",
                  }}
                />
                {filteredPool.map((c) => (
                  <div
                    key={c.candidate_id}
                    className="flex items-center justify-between rounded-lg px-4 py-2.5 border"
                    style={{ background: "#0f1012", borderColor: "rgba(255,255,255,0.06)" }}
                  >
                    <div>
                      <p className="text-xs font-medium text-white">{c.name}</p>
                      <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.35)" }}>
                        {Math.round(c.score * 100)}% match · rank #{c.rank}
                      </p>
                    </div>
                    <button
                      onClick={() => onAddCandidate(c)}
                      className="text-xs px-2 py-0.5 rounded transition-colors"
                      style={{ color: "#d5fa54", border: "1px solid rgba(213,250,84,0.25)" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(213,250,84,0.08)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      Add
                    </button>
                  </div>
                ))}
                {filteredPool.length === 0 && (
                  <p className="text-center text-xs py-2" style={{ color: "rgba(255,255,255,0.3)" }}>No matches</p>
                )}
              </div>
            )}
          </div>
        )}

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
                {eliminated_candidates.map((ec) => {
                  const alreadyAdded = allShortlistIds.has(ec.candidate_id);
                  return (
                    <div
                      key={ec.candidate_id}
                      className="flex items-center gap-3 rounded-lg px-4 py-3 border"
                      style={{
                        background: "#0f1012",
                        borderColor: "rgba(255,255,255,0.06)",
                      }}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white">{ec.name}</p>
                        <p className="mt-0.5 text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
                          {ec.elimination_reason}
                        </p>
                      </div>
                      {entries && !alreadyAdded && (
                        <button
                          onClick={() => onAddCandidate({
                            rank: 0,
                            candidate_id: ec.candidate_id,
                            name: ec.name,
                            score: 0,
                            explanation: `Override — originally eliminated: ${ec.elimination_reason}`,
                            feature_vector: { required_skills_overlap: 0, preferred_skills_overlap: 0, industry_preferred_match: 0, experience_delta: 0, seniority_match: 0, career_trajectory_score: 0, interview_score: 0, culture_fit_score: 0, management_match: 0, soft_constraint_score: 0 },
                            flagged_for_review: false,
                            constraint_matches: [],
                          })}
                          className="shrink-0 text-xs px-2 py-0.5 rounded transition-colors"
                          style={{ color: "#ff66c4", border: "1px solid rgba(255,102,196,0.25)" }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,102,196,0.08)")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          Override
                        </button>
                      )}
                      {entries && alreadyAdded && (
                        <span className="shrink-0 text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>Added</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
