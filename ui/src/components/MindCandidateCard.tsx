import { DownloadCvButton, ExpandableSection } from "./LiveCandidateCard";
import type { MindRunCandidate } from "../types";

const TIER_STYLE: Record<string, { bg: string; fg: string }> = {
  "strong match": { bg: "rgba(213,250,84,0.14)", fg: "#d5fa54" },
  "good match": { bg: "rgba(81,112,255,0.14)", fg: "#8ea1ff" },
  "possible match": { bg: "rgba(217,119,6,0.14)", fg: "#eab86b" },
  "weak match": { bg: "rgba(255,255,255,0.06)", fg: "rgba(255,255,255,0.45)" },
};

function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const s = TIER_STYLE[tier.toLowerCase()] ?? { bg: "rgba(255,255,255,0.06)", fg: "rgba(255,255,255,0.5)" };
  return (
    <span
      className="inline-flex shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: s.bg, color: s.fg }}
    >
      {tier}
    </span>
  );
}

interface RerankerSignal {
  verdict?: string;
  tier?: string;
  evidence?: string;
}

/** The reranker's own free-text justification for its top-line verdict — the
 * closest analogue to rec-engine's LLM `rationale` paragraph, so the two
 * columns read the same way at a glance. Prefers a "primary"-tier signal
 * with a "strong" verdict; falls back to the first signal with any evidence
 * text, then to the first strength bullet. */
function topRationale(c: MindRunCandidate): string {
  const signals = (c.reranker_signals ?? []) as RerankerSignal[];
  const primaryStrong = signals.find((s) => s.tier === "primary" && s.verdict === "strong" && s.evidence);
  const anyWithEvidence = signals.find((s) => s.evidence);
  const signal = primaryStrong ?? anyWithEvidence;
  if (signal?.evidence) return signal.evidence;
  return (c.reranker_strengths ?? [])[0] ?? "";
}

// Capped to roughly the same chip-row size as rec-engine's matched+missing
// skill row (LiveCandidateCard) — candidate_payload.skills can carry up to
// 40 entries, which would otherwise dwarf the equivalent rec-engine card.
const SKILLS_SHOWN = 14;

export default function MindCandidateCard({
  candidate,
  onClick,
}: {
  candidate: MindRunCandidate;
  onClick?: (candidateId: string, candidateName: string) => void;
}) {
  const c = candidate;
  const payload = c.candidate_payload;
  const filteredOut = c.hard_filter_pass === false;
  const rationale = topRationale(c);
  const bullhornId = String(c.candidate_id);
  const skills = payload?.skills ?? [];
  const shownSkills = skills.slice(0, SKILLS_SHOWN);
  const hiddenSkillCount = skills.length - shownSkills.length;

  return (
    <div
      className="rounded-lg border p-3"
      style={{
        borderColor: "rgba(255,255,255,0.08)",
        background: "#111214",
        opacity: filteredOut ? 0.55 : 1,
        cursor: onClick ? "pointer" : undefined,
      }}
      onClick={onClick ? () => onClick(bullhornId, c.candidate_name) : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono" style={{ color: "rgba(255,255,255,0.25)" }}>
            #{c.reranker_rank ?? "—"}
          </span>
          <span className="text-sm font-medium text-white">{c.candidate_name}</span>
          {filteredOut && (
            <span
              className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
              style={{ background: "rgba(220,38,38,0.12)", color: "#f87171" }}
            >
              Hard-filtered
            </span>
          )}
        </div>
        <TierBadge tier={c.reranker_tier} />
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
        {payload?.yearsExp != null && <span>{payload.yearsExp} yrs experience</span>}
        {payload?.title && <span>{payload.title}</span>}
        {payload?.currentCompany && <span>@ {payload.currentCompany}</span>}
        {c.reranker_score != null && <span>Score: {c.reranker_score}</span>}
        <span>BH #{bullhornId}</span>
        <DownloadCvButton bullhornId={bullhornId} />
      </div>

      {rationale && (
        <p className="mt-1.5 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>
          {rationale}
        </p>
      )}

      {shownSkills.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {shownSkills.map((s) => (
            <span
              key={s}
              className="rounded px-1.5 py-0.5 text-[10px]"
              style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54" }}
            >
              {s}
            </span>
          ))}
          {hiddenSkillCount > 0 && (
            <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.35)" }}>
              +{hiddenSkillCount} more
            </span>
          )}
        </div>
      )}

      <ExpandableSection label="Strengths" text={c.reranker_strengths?.join("\n")} />
      <ExpandableSection label="Concerns" text={c.reranker_concerns?.join("\n")} />
    </div>
  );
}
