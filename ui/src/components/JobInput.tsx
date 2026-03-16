import { useState } from "react";
import { Link2, FileText, Loader2 } from "lucide-react";
import { fetchJd } from "../lib/api";

interface Props {
  onSubmit: (jdText: string) => void;
  isLoading: boolean;
}

export default function JobInput({ onSubmit, isLoading }: Props) {
  const [tab, setTab] = useState<"url" | "text">("text");
  const [url, setUrl] = useState("");
  const [jdText, setJdText] = useState("");
  const [fetchingUrl, setFetchingUrl] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  async function handleFetch() {
    if (!url.trim()) return;
    setFetchingUrl(true);
    setFetchError(null);
    try {
      const result = await fetchJd(url.trim());
      setJdText(result.text);
      setTab("text");
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to fetch URL");
    } finally {
      setFetchingUrl(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Title */}
      <div className="flex-none">
        <p className="text-xs font-medium uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.35)" }}>
          Job Description
        </p>
      </div>

      {/* Tab toggle */}
      <div
        className="flex-none flex gap-1 rounded-lg p-1 w-fit"
        style={{ background: "rgba(255,255,255,0.05)" }}
      >
        {(["url", "text"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
            style={
              tab === t
                ? { background: "#d5fa54", color: "#0a0a0a" }
                : { color: "rgba(255,255,255,0.45)" }
            }
          >
            {t === "url" ? (
              <Link2 className="h-3 w-3" />
            ) : (
              <FileText className="h-3 w-3" />
            )}
            {t === "url" ? "URL" : "Text"}
          </button>
        ))}
      </div>

      {/* URL tab */}
      {tab === "url" && (
        <div className="flex flex-col gap-2 flex-1">
          <div className="flex gap-2">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
              placeholder="https://example.com/job-posting"
              className="flex-1 rounded-lg px-3 py-2 text-sm text-white placeholder-white/25 outline-none transition-all"
              style={{
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)",
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(213,250,84,0.5)")}
              onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
            />
            <button
              onClick={handleFetch}
              disabled={fetchingUrl || !url.trim()}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-semibold transition-all disabled:opacity-40"
              style={{ background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.8)" }}
            >
              {fetchingUrl && <Loader2 className="h-3 w-3 animate-spin" />}
              Fetch
            </button>
          </div>
          {fetchError && (
            <p className="text-xs text-red-400">{fetchError}</p>
          )}
        </div>
      )}

      {/* Text tab */}
      {tab === "text" && (
        <textarea
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          placeholder="Paste the job description here…"
          className="flex-1 min-h-0 resize-none rounded-lg px-3 py-2.5 text-sm text-white placeholder-white/25 outline-none transition-all"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(213,250,84,0.4)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)")}
        />
      )}

      {/* CTA */}
      <button
        onClick={() => jdText.trim() && onSubmit(jdText.trim())}
        disabled={isLoading || !jdText.trim()}
        className="flex-none w-full rounded-lg py-2.5 text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ background: "#d5fa54", color: "#0a0a0a" }}
      >
        Find Candidates
      </button>
    </div>
  );
}
