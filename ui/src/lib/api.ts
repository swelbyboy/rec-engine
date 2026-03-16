import type { CandidateRow, RecommendResult, StreamEvent } from "../types";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchJd(url: string): Promise<{ text: string; url: string }> {
  return apiFetch<{ text: string; url: string }>("/fetch-jd", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export async function recommend(params: {
  jd_text: string;
  profile?: string;
  top_n?: number;
}): Promise<RecommendResult> {
  return apiFetch<RecommendResult>("/recommend", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function listCandidates(): Promise<CandidateRow[]> {
  return apiFetch<CandidateRow[]>("/candidates");
}

export async function* recommendStream(params: {
  jd_text: string;
}): AsyncGenerator<StreamEvent> {
  const res = await fetch("/api/recommend/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as StreamEvent;
        } catch { /* skip malformed */ }
      }
    }
  }
}
