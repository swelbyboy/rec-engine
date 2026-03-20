import { Inbox, Users } from "lucide-react";
import type { ShortlistEntry } from "../types";
import CandidateCard from "./CandidateCard";

interface Props {
  shortlist: ShortlistEntry[] | null;
}

export default function HirerPanel({ shortlist }: Props) {
  if (!shortlist || shortlist.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-full"
          style={{ background: "rgba(255,255,255,0.05)" }}
        >
          <Inbox className="h-5 w-5" style={{ color: "rgba(255,255,255,0.3)" }} />
        </div>
        <div>
          <p className="text-sm font-medium" style={{ color: "rgba(255,255,255,0.5)" }}>
            Awaiting recruiter shortlist
          </p>
          <p className="mt-1 text-xs" style={{ color: "rgba(255,255,255,0.25)" }}>
            The recruiter will send a curated shortlist here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header — mirrors ResultsPanel */}
      <div
        className="flex-none flex items-center gap-2 px-5 py-3.5 border-b"
        style={{ borderColor: "rgba(255,255,255,0.07)" }}
      >
        <Users className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.35)" }} />
        <span className="text-xs font-medium text-white">
          {shortlist.length} shortlisted
        </span>
      </div>

      {/* Scrollable card list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 min-h-0">
        {shortlist.map((entry, i) => (
          <div key={entry.candidate.candidate_id}>
            <CandidateCard
              candidate={{ ...entry.candidate, rank: i + 1 }}
            />
            {/* Recruiter note — shown below card when present */}
            {entry.note && (
              <div
                className="mt-1 mx-1 rounded-b-lg px-3 py-2 text-xs"
                style={{
                  background: "rgba(213,250,84,0.05)",
                  border: "1px solid rgba(213,250,84,0.1)",
                  borderTop: "none",
                  color: "rgba(255,255,255,0.55)",
                }}
              >
                <span
                  className="mr-1.5 text-[10px] font-semibold uppercase tracking-widest"
                  style={{ color: "rgba(213,250,84,0.5)" }}
                >
                  Note
                </span>
                {entry.note}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
