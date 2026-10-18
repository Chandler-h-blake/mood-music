import type { z } from "zod";
import * as schema from "./api-schemas";
import type { ManualProfileUpdate, PCPlaybackActionInput } from "./api-types";
import { demoApi, isDemoMode } from "./demo-api";

export const PAGE_SIZE = 50;
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class MusicApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  validator: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  if (isDemoMode()) return demoApi<T>(path, init);
  const timeout = AbortSignal.timeout(150_000);
  const signal = init?.signal
    ? AbortSignal.any([init.signal, timeout])
    : timeout;
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      signal,
    });
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new MusicApiError(
      timeout.aborted
        ? "请求超时，请稍后重试。"
        : "无法连接本地服务，请检查服务是否启动。",
      "network.unavailable",
      0,
    );
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? data.detail
        : null;
    const message =
      typeof detail === "object" &&
      detail !== null &&
      "message" in detail &&
      typeof detail.message === "string"
        ? detail.message
        : "请求未能完成，请稍后重试。";
    const code =
      typeof detail === "object" &&
      detail !== null &&
      "code" in detail &&
      typeof detail.code === "string"
        ? detail.code
        : "request.failed";
    throw new MusicApiError(message, code, response.status);
  }
  const parsed = validator.safeParse(data);
  if (!parsed.success)
    throw new MusicApiError(
      "服务返回的数据格式不兼容，请确认前后端版本一致。",
      "response.invalid",
      response.status,
    );
  return parsed.data;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});
const sessions = (id: string) =>
  `/api/v1/search-sessions/${encodeURIComponent(id)}`;

export const musicApi = {
  library(page: number, query: string, signal?: AbortSignal) {
    const params = new URLSearchParams({
      page: String(page),
      pageSize: String(PAGE_SIZE),
    });
    if (query) params.set("q", query);
    return request(
      `/api/v1/library/songs?${params}`,
      schema.LibrarySongPageSchema,
      { signal },
    );
  },
  sync: () =>
    request(
      "/api/v1/library/sync",
      schema.LibrarySyncResultSchema,
      json("POST"),
    ),
  settings: () => request("/api/v1/settings", schema.ModelSettingsSchema),
  saveKey: (apiKey: string) =>
    request(
      "/api/v1/credentials/deepseek",
      schema.CredentialStatusSchema,
      json("PUT", { apiKey }),
    ),
  testKey: () =>
    request(
      "/api/v1/providers/deepseek/test",
      schema.CredentialStatusSchema,
      json("POST"),
    ),
  clearKey: () =>
    request(
      "/api/v1/credentials/deepseek",
      schema.CredentialStatusSchema,
      json("DELETE"),
    ),
  cookieStatus: () =>
    request(
      "/api/v1/credentials/qqmusic-cookie",
      schema.CredentialStatusSchema,
    ),
  saveCookie: (cookie: string) =>
    request(
      "/api/v1/credentials/qqmusic-cookie",
      schema.CredentialStatusSchema,
      json("PUT", { cookie }),
    ),
  testCookie: () =>
    request(
      "/api/v1/providers/qqmusic-cookie/test",
      schema.CredentialStatusSchema,
      json("POST"),
    ),
  clearCookie: () =>
    request(
      "/api/v1/credentials/qqmusic-cookie",
      schema.CredentialStatusSchema,
      json("DELETE"),
    ),
  latestJob: () =>
    request("/api/v1/profile-jobs/latest", schema.JobStatusSchema.nullable()),
  job: (id: string) =>
    request(`/api/v1/jobs/${encodeURIComponent(id)}`, schema.JobStatusSchema),
  startProfiling: () =>
    request(
      "/api/v1/profile-jobs",
      schema.JobStatusSchema,
      json("POST", { mode: "incremental" }),
    ),
  retryJob: (id: string) =>
    request(
      `/api/v1/jobs/${encodeURIComponent(id)}/retry`,
      schema.JobStatusSchema,
      json("POST"),
    ),
  profile: (id: string, signal?: AbortSignal) =>
    request(
      `/api/v1/library/songs/${encodeURIComponent(id)}/profile`,
      schema.SongProfileViewSchema.nullable(),
      { signal },
    ),
  saveProfile: (id: string, update: ManualProfileUpdate) =>
    request(
      `/api/v1/library/songs/${encodeURIComponent(id)}/profile`,
      schema.SongProfileViewSchema,
      json("PUT", update),
    ),
  history: (signal?: AbortSignal) =>
    request(
      "/api/v1/generated-playlists?page=0&pageSize=50",
      schema.PlaylistHistoryPageSchema,
      { signal },
    ),
  restore: (id: string) =>
    request(
      `/api/v1/generated-playlists/${encodeURIComponent(id)}/restore`,
      schema.TemporaryQueueSchema,
      json("POST"),
    ),
  generate: (description: string) =>
    request(
      "/api/v1/search-sessions",
      schema.TemporaryQueueSchema,
      json("POST", {
        description,
        matchingPolicy: "balanced",
        sortMode: "match",
        library: "liked",
      }),
    ),
  sort: (id: string, mode: "match" | "emotionCurve" | "random") =>
    request(
      `${sessions(id)}/sorts`,
      schema.TemporaryQueueSchema,
      json(
        "POST",
        mode === "emotionCurve"
          ? { mode, curve: { start: "calm", middle: "lifted", end: "settled" } }
          : { mode },
      ),
    ),
  remove: (id: string, candidateId: string) =>
    request(
      `${sessions(id)}/candidates/${encodeURIComponent(candidateId)}`,
      schema.TemporaryQueueSchema,
      json("DELETE"),
    ),
  similar: (id: string, candidateId: string) =>
    request(
      `${sessions(id)}/candidates/${encodeURIComponent(candidateId)}/similar`,
      schema.TemporaryQueueSchema,
      json("POST"),
    ),
  order: (id: string, candidateIds: string[]) =>
    request(
      `${sessions(id)}/candidate-order`,
      schema.TemporaryQueueSchema,
      json("PATCH", { candidateIds }),
    ),
  refine: (id: string, requirement: string) =>
    request(
      `${sessions(id)}/refinements`,
      schema.TemporaryQueueSchema,
      json("POST", { requirement }),
    ),
  playback: (signal?: AbortSignal) =>
    request("/api/v1/playback/state", schema.PCPlaybackStateSchema, { signal }),
  playQueue: (playlistId: string) =>
    request(
      "/api/v1/playback/queues",
      schema.PCPlaybackQueueResultSchema,
      json("POST", { playlistId }),
    ),
  control: (action: PCPlaybackActionInput["action"]) =>
    request(
      "/api/v1/playback/actions",
      schema.PCPlaybackActionResultSchema,
      json("POST", { action }),
    ),
};
