import type { CandidateRow, FeatureVector, FeedbackRecord, ModelStatus, RecommendResult, RetrainResult, StreamEvent } from "../types";

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

export const FEATURE_ORDER: (keyof FeatureVector)[] = [
  "required_skills_overlap",
  "preferred_skills_overlap",
  "industry_preferred_match",
  "experience_delta",
  "seniority_match",
  "career_trajectory_score",
  "interview_score",
  "culture_fit_score",
  "management_match",
  "soft_constraint_score",
];

export function featureVectorToArray(fv: FeatureVector): number[] {
  return FEATURE_ORDER.map((k) => fv[k]);
}

export async function submitFeedback(records: FeedbackRecord[]): Promise<{ saved: number; total_feedback: number }> {
  return apiFetch("/feedback", {
    method: "POST",
    body: JSON.stringify({ records }),
  });
}

export async function getModelStatus(): Promise<ModelStatus> {
  return apiFetch<ModelStatus>("/model/status");
}

export interface RegressionDetail {
  logistic: { old_auc: number; new_auc: number };
  gbt: { old_auc: number; new_auc: number };
}

export class RegressionBlockedError extends Error {
  regression: RegressionDetail;
  constructor(regression: RegressionDetail, message: string) {
    super(message);
    this.regression = regression;
  }
}

export async function retrainModels(force = false): Promise<RetrainResult> {
  const res = await fetch(`/api/retrain?force=${force}`, { method: "POST" });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({ detail: { message: "Regression detected", regression: {} } }));
    const detail = body.detail ?? body;
    throw new RegressionBlockedError(detail.regression, detail.message ?? "Regression detected");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<RetrainResult>;
}

export interface ModelMetrics {
  n_test: number;
  feature_names: string[];
  logistic?: { auc: number; brier_score: number; log_loss: number };
  gbt?: { auc: number; brier_score: number; log_loss: number };
}

export async function getModelMetrics(): Promise<ModelMetrics> {
  return apiFetch<ModelMetrics>("/model/metrics");
}

export interface ModelWeights {
  feature_names: string[];
  logistic?: { weights: number[]; type: "coefficients" };
  gbt?: { weights: number[]; type: "importances" };
}

export async function getModelWeights(): Promise<ModelWeights> {
  return apiFetch<ModelWeights>("/model/weights");
}

export async function uploadTrainingData(file: File): Promise<{ records_added: number; total_records: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/training-data/upload", { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
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
