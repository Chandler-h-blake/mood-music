export const DEMO_BUILD_ENABLED = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

type DemoSong = {
  id: string;
  sourceTrackId: string;
  title: string;
  artists: { name: string }[];
  album: string;
  durationMs: number;
};

type DemoQueueSong = DemoSong & {
  candidateId: string;
  songId: string;
  score: number;
  semanticScore: number;
  featureScore: number;
};

const songs: DemoSong[] = [
  ["夜航灯", "林屿", "沿海公路", 238000],
  ["微风经过站台", "夏禾", "慢慢抵达", 214000],
  ["城市入睡以后", "南栖", "凌晨三点", 267000],
  ["没有寄出的明信片", "陈默", "远方来信", 225000],
  ["雨停在清晨", "白昼乐队", "潮湿季节", 246000],
  ["低空飞行", "雾岛", "轻盈轨道", 201000],
  ["晚霞倒带", "时差", "橘色时刻", 232000],
  ["无人的咖啡馆", "周野", "留白", 219000],
  ["玻璃海", "拾光计划", "透明夏天", 252000],
  ["星光慢车", "北岸", "长途旅行", 241000],
  ["星期五出口", "青柠汽水", "下班以后", 196000],
  ["把噪音关在门外", "静默频道", "专注模式", 288000],
].map(([title, artist, album, duration], index) => ({
  id: `demo-song-${index + 1}`,
  sourceTrackId: `demo-track-${index + 1}`,
  title: String(title),
  artists: [{ name: String(artist) }],
  album: String(album),
  durationMs: Number(duration),
}));

export const demoLibraryPage = { page: 0, pageSize: 50, total: songs.length, songs };
export const demoSettings = { chatProvider: "demo", chatModel: "MoodMusic Demo", embeddingProvider: "demo", embeddingModel: "BGE-M3 Demo", embeddingDimensions: 1024, apiKeyConfigured: true };

let queueSongs: DemoQueueSong[] = songs.slice(0, 8).map((song, index) => ({
  ...song,
  candidateId: `demo-candidate-${index + 1}`,
  songId: song.id,
  score: 0.94 - index * 0.035,
  semanticScore: 0.96 - index * 0.034,
  featureScore: 0.91 - index * 0.03,
}));
let sortMode = "match";
let playbackIndex = 0;
let playbackStatus: "playing" | "paused" | "stopped" = "stopped";

export function isDemoMode() {
  if (DEMO_BUILD_ENABLED) return true;
  return typeof window !== "undefined"
    && new URLSearchParams(window.location.search).get("demo") === "1";
}

function queue(description = "凌晨开车，有一点孤独，但不要太悲伤") {
  return {
    sessionId: "demo-session",
    playlistId: "demo-playlist",
    name: "深夜公路 · 克制的孤独",
    description,
    intent: {
      summary: "安静、流动、略带孤独感，但保持温暖",
      exclusions: ["过度悲伤", "高强度节拍"],
      threshold: 0.68,
      maxEnergy: 0.72,
    },
    candidateSetHash: "demo-candidate-set",
    evaluatedCount: songs.length,
    matchedCount: queueSongs.length,
    songs: queueSongs,
    sortMode,
    randomSeed: sortMode === "random" ? 20260915 : null,
    curve: sortMode === "emotionCurve"
      ? { start: "calm", middle: "lifted", end: "settled" }
      : null,
    createdAt: new Date().toISOString(),
  };
}

function jsonBody(init?: RequestInit): Record<string, unknown> {
  if (typeof init?.body !== "string") return {};
  try { return JSON.parse(init.body) as Record<string, unknown>; }
  catch { return {}; }
}

function result<T>(value: unknown): T {
  return value as T;
}

export async function demoApi<T>(path: string, init?: RequestInit): Promise<T> {
  await new Promise((resolve) => window.setTimeout(resolve, 120));
  const url = new URL(path, "http://demo.local");
  const method = init?.method ?? "GET";
  const body = jsonBody(init);

  if (url.pathname === "/api/v1/library/songs") {
    const page = Number(url.searchParams.get("page") ?? 0);
    const pageSize = Number(url.searchParams.get("pageSize") ?? 50);
    const queryText = (url.searchParams.get("q") ?? "").toLocaleLowerCase("zh-CN");
    const filtered = songs.filter((song) => !queryText || [song.title, song.album, ...song.artists.map((artist) => artist.name)].some((value) => value.toLocaleLowerCase("zh-CN").includes(queryText)));
    return result<T>({ page, pageSize, total: filtered.length, songs: filtered.slice(page * pageSize, (page + 1) * pageSize) });
  }
  if (url.pathname === "/api/v1/library/sync" && method === "POST") return result<T>({ uniqueCount: songs.length });
  if (url.pathname === "/api/v1/settings") return result<T>(demoSettings);
  if (url.pathname.startsWith("/api/v1/credentials/") || url.pathname.startsWith("/api/v1/providers/")) return result<T>({ status: "ok" });
  if (url.pathname === "/api/v1/profile-jobs" || url.pathname.includes("/retry") || url.pathname.startsWith("/api/v1/jobs/")) return result<T>({ jobId: "demo-job", status: "succeeded", total: songs.length, completed: songs.length, failed: 0, lastError: null });
  if (url.pathname === "/api/v1/search-sessions" && method === "POST") return result<T>(queue(String(body.description ?? "演示队列")));
  if (url.pathname === "/api/v1/generated-playlists/demo-history/restore") {
    sortMode = "restored";
    return result<T>(queue("周五下班路上，轻快松弛，别太吵"));
  }
  if (url.pathname === "/api/v1/generated-playlists") return result<T>({ page: 0, pageSize: 50, total: 1, playlists: [{ playlistId: "demo-history", sessionId: "demo-session", name: "周五傍晚的松弛感", description: "轻快、有空气感，不要太吵", sortMode: "emotionCurve", songCount: 7, createdAt: "2026-09-14T10:30:00.000Z" }] });
  if (url.pathname.endsWith("/sorts")) {
    sortMode = String(body.mode ?? "match");
    if (sortMode === "random") queueSongs = [...queueSongs].sort((a, b) => a.title.localeCompare(b.title, "zh-CN"));
    else if (sortMode === "emotionCurve") queueSongs = [...queueSongs].reverse();
    else queueSongs = [...queueSongs].sort((a, b) => b.score - a.score);
    return result<T>(queue());
  }
  if (url.pathname.endsWith("/candidate-order")) {
    const ids = Array.isArray(body.candidateIds) ? body.candidateIds.map(String) : [];
    queueSongs = ids.map((id) => queueSongs.find((song) => song.candidateId === id)).filter((song): song is DemoQueueSong => Boolean(song));
    sortMode = "manual";
    return result<T>(queue());
  }
  if (url.pathname.endsWith("/refinements")) {
    queueSongs = queueSongs.slice(0, Math.max(3, queueSongs.length - 1));
    return result<T>(queue(String(body.requirement ?? "追加要求")));
  }
  const candidateMatch = url.pathname.match(/\/candidates\/([^/]+)(\/similar)?$/);
  if (candidateMatch && method === "DELETE") {
    queueSongs = queueSongs.filter((song) => song.candidateId !== candidateMatch[1]);
    return result<T>(queue());
  }
  if (candidateMatch?.[2]) {
    const selected = queueSongs.find((song) => song.candidateId === candidateMatch[1]);
    if (selected) queueSongs = [selected, ...queueSongs.filter((song) => song !== selected)];
    sortMode = "similar";
    return result<T>(queue());
  }
  if (url.pathname === "/api/v1/playback/queues") {
    playbackIndex = 0; playbackStatus = "playing";
    return result<T>({ status: "completed", acceptedCount: queueSongs.length, title: queueSongs[0]?.title ?? "", artist: queueSongs[0]?.artists[0]?.name ?? null, observed: true, message: "演示播放器已启动" });
  }
  if (url.pathname === "/api/v1/playback/actions") {
    const action = String(body.action);
    if (action === "next") playbackIndex = Math.min(queueSongs.length - 1, playbackIndex + 1);
    if (action === "previous") playbackIndex = Math.max(0, playbackIndex - 1);
    if (action === "pause") playbackStatus = "paused";
    if (action === "play") playbackStatus = "playing";
    const current = queueSongs[playbackIndex];
    return result<T>({ status: "completed", action, accepted: true, observed: true, playbackStatus, title: current?.title ?? null, artist: current?.artists[0]?.name ?? null, message: "演示操作已完成" });
  }
  if (url.pathname === "/api/v1/playback/state") {
    const current = queueSongs[playbackIndex];
    return result<T>({ status: playbackStatus, title: current?.title ?? null, artist: current?.artists[0]?.name ?? null, album: current?.album ?? null, positionMs: 42000, durationMs: current?.durationMs ?? null, message: "演示播放器" });
  }
  throw new Error(`演示模式尚未实现接口：${method} ${url.pathname}`);
}
