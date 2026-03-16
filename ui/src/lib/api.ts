import type { RecommendResult } from "../types";

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
