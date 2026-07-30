import LiveCandidateCard from "./LiveCandidateCard";
import type { LiveEliminatedCandidate, LiveRankedCandidate } from "../types";

interface LiveCandidateListProps {
  ranked: LiveRankedCandidate[];
  eliminated: LiveEliminatedCandidate[];
}

export default function LiveCandidateList({ ranked, eliminated }: LiveCandidateListProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5">
      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          Ranked candidates ({ranked.length})
        </p>
        <div className="flex flex-col gap-2">
          {ranked.map((c, i) => (
            <LiveCandidateCard key={c.candidate_id} candidate={c} rank={i + 1} />
          ))}
        </div>
      </div>

      {eliminated.length > 0 && (
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Eliminated ({eliminated.length})
          </p>
          <div className="flex flex-col gap-1.5">
            {eliminated.map((c) => (
              <div key={c.candidate_id} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
                <p className="text-xs font-medium" style={{ color: "rgba(255,255,255,0.55)" }}>{c.name}</p>
                {c.reasons.map((r, i) => (
                  <p key={i} className="mt-0.5 text-[11px]" style={{ color: "rgba(255,255,255,0.35)" }}>{r}</p>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
