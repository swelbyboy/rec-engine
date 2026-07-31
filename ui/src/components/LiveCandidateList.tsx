import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import LiveCandidateCard from "./LiveCandidateCard";
import type { LiveEliminatedCandidate, LiveRankedCandidate } from "../types";

interface LiveCandidateListProps {
  ranked: LiveRankedCandidate[];
  eliminated: LiveEliminatedCandidate[];
}

function matchesQuery(c: LiveRankedCandidate, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if (c.name.toLowerCase().includes(q)) return true;
  // Older persisted runs predate matched_skills/missing_required_skills.
  const skills = [...(c.matched_skills ?? []), ...(c.missing_required_skills ?? [])];
  return skills.some((s) => s.toLowerCase().includes(q));
}

export default function LiveCandidateList({ ranked, eliminated }: LiveCandidateListProps) {
  const [query, setQuery] = useState("");

  // Rank numbers reflect the full ranked order, computed before filtering —
  // filtering shouldn't renumber #1/#2/... out from under a candidate.
  const numbered = useMemo(() => ranked.map((c, i) => ({ candidate: c, rank: i + 1 })), [ranked]);
  const filtered = useMemo(() => numbered.filter(({ candidate }) => matchesQuery(candidate, query)), [numbered, query]);

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5">
      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Ranked candidates ({query ? `${filtered.length} of ${ranked.length}` : ranked.length})
          </p>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2"
              style={{ color: "rgba(255,255,255,0.3)" }}
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name or skill…"
              className="w-48 rounded-lg border bg-transparent py-1 pl-7 pr-6 text-xs outline-none"
              style={{ borderColor: "rgba(255,255,255,0.12)", color: "white" }}
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2"
                style={{ color: "rgba(255,255,255,0.3)" }}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {filtered.length === 0 ? (
            <p className="text-xs" style={{ color: "rgba(255,255,255,0.3)" }}>No candidates match "{query}".</p>
          ) : (
            filtered.map(({ candidate, rank }) => (
              <LiveCandidateCard key={candidate.candidate_id} candidate={candidate} rank={rank} />
            ))
          )}
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
