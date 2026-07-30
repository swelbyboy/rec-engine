import type { LiveRankedCandidate, LiveVerdict } from "../types";

const VERDICT_STYLE: Record<LiveVerdict, { bg: string; fg: string; label: string }> = {
  strong_match: { bg: "rgba(213,250,84,0.14)", fg: "#d5fa54", label: "Strong match" },
  good_match: { bg: "rgba(81,112,255,0.14)", fg: "#8ea1ff", label: "Good match" },
  possible: { bg: "rgba(217,119,6,0.14)", fg: "#eab86b", label: "Possible" },
  weak_match: { bg: "rgba(255,255,255,0.06)", fg: "rgba(255,255,255,0.45)", label: "Weak match" },
};

export function VerdictBadge({ verdict }: { verdict: LiveVerdict }) {
  const s = VERDICT_STYLE[verdict];
  return (
    <span
      className="inline-flex shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

export default function LiveCandidateCard({ candidate, rank }: { candidate: LiveRankedCandidate; rank: number }) {
  const c = candidate;
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.08)", background: "#111214" }}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono" style={{ color: "rgba(255,255,255,0.25)" }}>#{rank}</span>
          <span className="text-sm font-medium text-white">{c.name}</span>
          {c.flagged_for_review && (
            <span
              className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
              style={{ background: "rgba(217,119,6,0.14)", color: "#eab86b" }}
            >
              Flagged
            </span>
          )}
        </div>
        <VerdictBadge verdict={c.verdict} />
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
        <span>{c.years_experience} yrs experience</span>
        <span className="capitalize">{c.seniority_level}</span>
        {c.bullhorn_url ? (
          <a
            href={c.bullhorn_url}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2"
            style={{ color: "#8ea1ff" }}
          >
            BH #{c.bullhorn_id}
          </a>
        ) : (
          <span>BH #{c.bullhorn_id}</span>
        )}
      </div>

      <p className="mt-1.5 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>{c.rationale}</p>

      {(c.matched_skills.length > 0 || c.missing_required_skills.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1">
          {c.matched_skills.map((s) => (
            <span
              key={`matched-${s}`}
              className="rounded px-1.5 py-0.5 text-[10px]"
              style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54" }}
            >
              {s}
            </span>
          ))}
          {c.missing_required_skills.map((s) => (
            <span
              key={`missing-${s}`}
              className="rounded px-1.5 py-0.5 text-[10px] line-through"
              style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.35)" }}
            >
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
