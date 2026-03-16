import { useEffect, useState } from "react";
import { listCandidates } from "../lib/api";
import type { CandidateRow } from "../types";

function seniorityLabel(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1).replace("_", " ");
}

function trajectoryLabel(t: string) {
  const map: Record<string, string> = {
    ascending: "↑ Ascending",
    lateral: "→ Lateral",
    mixed: "~ Mixed",
  };
  return map[t] ?? t;
}

function trajectoryColor(t: string) {
  if (t === "ascending") return "#d5fa54";
  if (t === "lateral") return "rgba(255,255,255,0.45)";
  return "#5170ff";
}

export default function CandidatesTable() {
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCandidates()
      .then(setCandidates)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm" style={{ color: "rgba(255,255,255,0.3)" }}>Loading candidates…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm text-red-400">{error}</span>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
      <table className="w-full text-xs">
        <thead>
          <tr style={{ background: "rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
            {["Name", "Experience", "Seniority", "Trajectory", "Skills", "Industries"].map((h) => (
              <th key={h} className="px-3 py-2.5 text-left font-semibold uppercase tracking-widest"
                style={{ color: "rgba(255,255,255,0.3)", fontSize: "10px" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {candidates.map((c, i) => (
            <tr
              key={c.id}
              className="border-t"
              style={{
                borderColor: "rgba(255,255,255,0.05)",
                background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
              }}
            >
              <td className="px-3 py-2.5 font-medium text-white whitespace-nowrap">{c.name}</td>
              <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: "rgba(255,255,255,0.55)" }}>
                {c.years_experience}y
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <span
                  className="inline-flex rounded px-1.5 py-0.5"
                  style={{ background: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.55)" }}
                >
                  {seniorityLabel(c.seniority_level)}
                </span>
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap font-medium" style={{ color: trajectoryColor(c.career_trajectory) }}>
                {trajectoryLabel(c.career_trajectory)}
              </td>
              <td className="px-3 py-2.5 max-w-xs">
                <div className="flex flex-wrap gap-1">
                  {c.skills.slice(0, 6).map((s) => (
                    <span
                      key={s}
                      className="inline-flex rounded px-1.5 py-0.5 text-[10px]"
                      style={{ background: "rgba(81,112,255,0.12)", color: "#5170ff" }}
                    >
                      {s}
                    </span>
                  ))}
                  {c.skills.length > 6 && (
                    <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>
                      +{c.skills.length - 6}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-3 py-2.5" style={{ color: "rgba(255,255,255,0.45)" }}>
                {c.industries.slice(0, 2).join(", ")}
                {c.industries.length > 2 && (
                  <span style={{ color: "rgba(255,255,255,0.25)" }}> +{c.industries.length - 2}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
