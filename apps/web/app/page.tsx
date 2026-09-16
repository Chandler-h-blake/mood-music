"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Clock3, Database, GitCompareArrows, GripVertical, History, KeyRound, LibraryBig, ListMusic, LoaderCircle, Music2, Pause, Play, RefreshCw, Search, Settings2, Shuffle, SkipBack, SkipForward, Sparkles, Trash2, WandSparkles, Waves, WifiOff } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import { DEMO_BUILD_ENABLED, demoApi, demoLibraryPage, demoSettings, isDemoMode } from "@/lib/demo-api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PAGE_SIZE = 50;
type View = "library" | "discover" | "queue" | "player" | "history" | "settings";
type Artist = { name: string };
type LibrarySong = { id: string; sourceTrackId: string; title: string; artists: Artist[]; album: string | null; durationMs: number | null };
type LibraryPage = { page: number; pageSize: number; total: number; songs: LibrarySong[] };
type ModelSettings = { chatProvider: string; chatModel: string; embeddingProvider: string; embeddingModel: string; embeddingDimensions: number; apiKeyConfigured: boolean };
type Job = { jobId: string; status: string; total: number; completed: number; failed: number; lastError: string | null };
type QueueSong = LibrarySong & { candidateId: string; songId: string; score: number; semanticScore: number; featureScore: number };
type TemporaryQueue = { sessionId: string; playlistId: string; name: string; description: string; intent: { summary: string; exclusions: string[]; threshold: number; requiredVocalModes?: string[]; excludedVocalModes?: string[]; allowedLanguages?: string[]; excludedLanguages?: string[]; instrumentalAllowed?: boolean | null; maxEnergy?: number | null }; candidateSetHash: string; evaluatedCount: number; matchedCount: number; songs: QueueSong[]; sortMode: string; randomSeed: number | null; curve: { start: string; middle: string; end: string } | null; createdAt: string | null };
type PlaylistSummary = { playlistId: string; sessionId: string; name: string; description: string; sortMode: string; songCount: number; createdAt: string };
type PlaylistHistoryPage = { page: number; pageSize: number; total: number; playlists: PlaylistSummary[] };
type PlaybackQueueResult = { status: "completed" | "acceptedUnconfirmed"; acceptedCount: number; title: string; artist: string | null; observed: boolean; message: string };
type PlaybackState = { status: "playing" | "paused" | "stopped" | "closed" | "unavailable"; title: string | null; artist: string | null; album: string | null; positionMs: number | null; durationMs: number | null; message: string };
type PlaybackAction = "play" | "pause" | "next" | "previous";
type PlaybackActionResult = { status: "completed" | "acceptedUnconfirmed"; action: PlaybackAction; accepted: boolean; observed: boolean; playbackStatus: PlaybackState["status"]; title: string | null; artist: string | null; message: string };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (isDemoMode()) return demoApi<T>(path, init);
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: { message?: string } } | null;
    throw new Error(body?.detail?.message ?? "本地音乐服务暂时不可用");
  }
  return (await response.json()) as T;
}

function formatDuration(durationMs: number | null) {
  if (durationMs === null) return "—";
  const seconds = Math.floor(durationMs / 1000);
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
}

const examples = ["凌晨开车，有一点孤独，但不要太悲伤", "周五下班路上，轻快松弛，别太吵", "专注写代码，有流动感，尽量少人声"];
const subscribeDemoMode = () => () => undefined;

export default function Home() {
  const demoMode = useSyncExternalStore(subscribeDemoMode, isDemoMode, isDemoMode);
  const [view, setView] = useState<View>("library");
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [library, setLibrary] = useState<LibraryPage | null>(DEMO_BUILD_ENABLED ? demoLibraryPage : null);
  const [loading, setLoading] = useState(!DEMO_BUILD_ENABLED);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<ModelSettings | null>(DEMO_BUILD_ENABLED ? demoSettings : null);
  const [apiKey, setApiKey] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [feeling, setFeeling] = useState(examples[0]);
  const [generating, setGenerating] = useState(false);
  const [queue, setQueue] = useState<TemporaryQueue | null>(null);
  const [queueBusy, setQueueBusy] = useState(false);
  const [history, setHistory] = useState<PlaylistHistoryPage | null>(null);
  const [playerActive, setPlayerActive] = useState(false);
  const [playerBusy, setPlayerBusy] = useState(false);
  const [playback, setPlayback] = useState<PlaybackState | null>(null);

  const loadLibrary = useCallback(async () => {
    setLoading(true); setError(null);
    const params = new URLSearchParams({ page: String(page), pageSize: String(PAGE_SIZE) });
    if (query) params.set("q", query);
    try { setLibrary(await api<LibraryPage>(`/api/v1/library/songs?${params}`)); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "无法读取本地曲库"); }
    finally { setLoading(false); }
  }, [page, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadLibrary(), 0);
    return () => window.clearTimeout(timer);
  }, [loadLibrary]);
  useEffect(() => { void api<ModelSettings>("/api/v1/settings").then(setSettings).catch(() => undefined); }, []);
  useEffect(() => {
    if (view !== "history") return;
    void api<PlaylistHistoryPage>("/api/v1/generated-playlists?page=0&pageSize=50").then(setHistory).catch((historyError) => toast.error(historyError instanceof Error ? historyError.message : "无法读取队列历史"));
  }, [view]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      void api<Job>(`/api/v1/jobs/${job.jobId}`).then((next) => {
        setJob(next);
        if (next.status === "succeeded" && next.failed) toast.warning(`主体画像已完成，${next.failed} 首可稍后重试`);
        else if (next.status === "succeeded") toast.success("全部待处理歌曲已完成画像");
        if (next.status === "failed") toast.error(next.lastError ?? "画像任务失败");
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job]);
  useEffect(() => {
    if (!playerActive) return;
    const refresh = () => void api<PlaybackState>("/api/v1/playback/state").then(setPlayback).catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [playerActive]);

  const totalPages = Math.max(1, Math.ceil((library?.total ?? 0) / PAGE_SIZE));
  const profileProgress = job?.total ? Math.round(((job.completed + job.failed) / job.total) * 100) : job?.status === "succeeded" ? 100 : 0;
  const title = { library: "我的喜欢", discover: "AI 选歌", queue: "临时队列", player: "播放器", history: "队列历史", settings: "模型设置" }[view];
  const subtitle = { library: "QQ 音乐收藏的本地镜像", discover: "描述一种感觉，从全部喜欢中找到它", queue: "排序、删减、拖动或继续描述", player: "由 MoodMusic 掌握播放顺序，QQ 音乐负责声音输出", history: "恢复每一次筛选、排序和人工调整快照", settings: "密钥只保存在本机 Windows 凭据存储" }[view];

  async function syncLibrary() {
    setSyncing(true);
    try {
      const result = await api<{ uniqueCount: number }>("/api/v1/library/sync", { method: "POST" });
      setPage(0); await loadLibrary(); toast.success(`同步完成，共 ${result.uniqueCount.toLocaleString("zh-CN")} 首歌曲`);
    } catch (syncError) { toast.error(syncError instanceof Error ? syncError.message : "同步失败"); }
    finally { setSyncing(false); }
  }

  async function saveKey(event: FormEvent) {
    event.preventDefault(); setSavingKey(true);
    try {
      await api("/api/v1/credentials/deepseek", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ apiKey }) });
      await api("/api/v1/providers/deepseek/test", { method: "POST" });
      setSettings(await api<ModelSettings>("/api/v1/settings")); setApiKey(""); toast.success("API Key 已安全保存，模型连接有效");
    } catch (keyError) { toast.error(keyError instanceof Error ? keyError.message : "API Key 设置失败"); }
    finally { setSavingKey(false); }
  }

  async function startProfiling() {
    try {
      const retrying = job?.status === "failed";
      const result = retrying
        ? await api<Job>(`/api/v1/jobs/${job.jobId}/retry`, { method: "POST" })
        : await api<Job>("/api/v1/profile-jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "incremental" }) });
      setJob(result);
      toast.success(retrying ? `将从 ${result.completed} / ${result.total} 继续处理` : result.total ? `已开始为 ${result.total} 首歌曲建立画像` : "画像已经是最新状态");
    } catch (profileError) { toast.error(profileError instanceof Error ? profileError.message : "无法创建画像任务"); }
  }

  async function generateQueue(event: FormEvent) {
    event.preventDefault(); if (feeling.trim().length < 2) return; setGenerating(true);
    try {
      const result = await api<TemporaryQueue>("/api/v1/search-sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description: feeling.trim(), matchingPolicy: "balanced", sortMode: "match", library: "liked" }) });
      setQueue(result); setView("queue"); toast.success(`已从 ${result.evaluatedCount} 首画像歌曲中选出 ${result.matchedCount} 首`);
    } catch (searchError) { toast.error(searchError instanceof Error ? searchError.message : "AI 选歌失败"); }
    finally { setGenerating(false); }
  }

  async function updateQueue(path: string, init: RequestInit, success: string) {
    setQueueBusy(true);
    try {
      const result = await api<TemporaryQueue>(path, init);
      setQueue(result); setView("queue"); toast.success(success);
    } catch (queueError) { toast.error(queueError instanceof Error ? queueError.message : "队列更新失败"); }
    finally { setQueueBusy(false); }
  }

  async function sortQueue(mode: "match" | "emotionCurve" | "random") {
    const body = mode === "emotionCurve" ? { mode, curve: { start: "calm", middle: "lifted", end: "settled" } } : { mode };
    await updateQueue(`/api/v1/search-sessions/${queue?.sessionId}/sorts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, mode === "match" ? "已恢复匹配度排序" : mode === "random" ? "已生成可复现随机顺序" : "已生成平滑情绪曲线");
  }

  async function removeCandidate(candidateId: string) {
    await updateQueue(`/api/v1/search-sessions/${queue?.sessionId}/candidates/${candidateId}`, { method: "DELETE" }, "已从当前会话移除歌曲");
  }

  async function findSimilar(candidateId: string) {
    await updateQueue(`/api/v1/search-sessions/${queue?.sessionId}/candidates/${candidateId}/similar`, { method: "POST" }, "已按与该歌曲的相似度重新排列");
  }

  async function saveOrder(candidateIds: string[]) {
    await updateQueue(`/api/v1/search-sessions/${queue?.sessionId}/candidate-order`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidateIds }) }, "已保存人工顺序");
  }

  async function refineQueue(requirement: string) {
    await updateQueue(`/api/v1/search-sessions/${queue?.sessionId}/refinements`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requirement }) }, "已按追加要求重新筛选全部画像歌曲");
  }

  async function restorePlaylist(playlistId: string) {
    await updateQueue(`/api/v1/generated-playlists/${playlistId}/restore`, { method: "POST" }, "已把历史快照恢复为可编辑的当前队列");
  }

  async function playQueue() {
    if (!queue) return;
    setQueueBusy(true);
    try {
      const result = await api<PlaybackQueueResult>("/api/v1/playback/queues", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playlistId: queue.playlistId }) });
      setPlayerActive(true);
      setPlayback({ status: result.observed ? "playing" : "unavailable", title: result.title, artist: result.artist, album: null, positionMs: 0, durationMs: null, message: result.message });
      setView("player");
      if (result.observed) toast.success(`QQ 音乐正在播放：${result.title}`);
      else toast.warning(result.message);
    } catch (playbackError) { toast.error(playbackError instanceof Error ? playbackError.message : "无法在 QQ 音乐中开始播放"); }
    finally { setQueueBusy(false); }
  }

  async function controlPlayback(action: PlaybackAction) {
    setPlayerBusy(true);
    try {
      const result = await api<PlaybackActionResult>("/api/v1/playback/actions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
      setPlayback((current) => ({ status: result.playbackStatus, title: result.title ?? current?.title ?? null, artist: result.artist ?? current?.artist ?? null, album: current?.album ?? null, positionMs: action === "next" || action === "previous" ? 0 : current?.positionMs ?? null, durationMs: action === "next" || action === "previous" ? null : current?.durationMs ?? null, message: result.message }));
      if (!result.accepted) toast.info(result.message);
    } catch (controlError) { toast.error(controlError instanceof Error ? controlError.message : "播放器控制失败"); }
    finally { setPlayerBusy(false); }
  }

  return <SidebarProvider style={{ "--sidebar-width": "15rem" } as React.CSSProperties} className="bg-[#07100e]">
    <Sidebar collapsible="icon" className="border-r-0 bg-[#07100e]">
      <SidebarHeader className="px-3 py-5"><div className="flex items-center gap-3 px-1"><div className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#29e68b] text-[#04110c] shadow-[0_0_28px_rgba(41,230,139,0.25)]"><Music2 className="size-5" /></div><div className="min-w-0 group-data-[collapsible=icon]:hidden"><p className="truncate text-[15px] font-semibold text-white">MoodMusic</p><p className="truncate text-xs text-white/40">我的音乐工作台</p></div></div></SidebarHeader>
      <SidebarContent><SidebarGroup><SidebarGroupLabel className="text-white/35">音乐</SidebarGroupLabel><SidebarGroupContent><SidebarMenu>
        <NavItem icon={<LibraryBig />} label="我的喜欢" active={view === "library"} onClick={() => setView("library")} />
        <NavItem icon={<Sparkles />} label="AI 选歌" active={view === "discover"} onClick={() => setView("discover")} />
        <NavItem icon={<ListMusic />} label="临时队列" active={view === "queue"} onClick={() => setView("queue")} />
        <NavItem icon={<Play />} label="播放器" active={view === "player"} onClick={() => setView("player")} />
        <NavItem icon={<History />} label="队列历史" active={view === "history"} onClick={() => setView("history")} />
      </SidebarMenu></SidebarGroupContent></SidebarGroup></SidebarContent>
      <SidebarFooter className="px-3 pb-4"><SidebarMenu><NavItem icon={<Settings2 />} label="模型设置" active={view === "settings"} onClick={() => setView("settings")} /></SidebarMenu><div className="mt-2 flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2.5 text-xs text-white/45 group-data-[collapsible=icon]:hidden"><span className="size-1.5 rounded-full bg-[#29e68b]" />曲库与密钥保存在本机</div></SidebarFooter>
    </Sidebar>
    <SidebarInset className="min-w-0 bg-[#0b1412] text-[#eff8f3]">
      <header className="sticky top-0 z-10 flex min-h-20 items-center justify-between border-b border-white/[0.07] bg-[#0b1412]/90 px-4 backdrop-blur-xl sm:px-7"><div className="flex min-w-0 items-center gap-3"><SidebarTrigger className="text-white/60 hover:bg-white/[0.06] hover:text-white" /><div><div className="flex items-center gap-2"><h1 className="text-lg font-semibold sm:text-xl">{title}</h1>{demoMode ? <Badge className="border-amber-300/20 bg-amber-300/10 text-amber-200">演示模式</Badge> : null}</div><p className="mt-0.5 hidden text-sm text-white/42 sm:block">{demoMode ? "使用虚构示例数据，不会连接 QQ 音乐或外部模型" : subtitle}</p></div></div>{view === "library" ? <Button onClick={() => void syncLibrary()} disabled={syncing} className="h-10 rounded-xl bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"><RefreshCw className={syncing ? "animate-spin" : ""} />{syncing ? "正在同步" : demoMode ? "模拟同步" : "同步 QQ 音乐"}</Button> : null}</header>
      <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
        {view === "library" ? <LibraryView library={library} loading={loading} error={error} page={page} totalPages={totalPages} query={query} searchDraft={searchDraft} setSearchDraft={setSearchDraft} submitSearch={(event) => { event.preventDefault(); setPage(0); setQuery(searchDraft.trim()); }} setPage={setPage} reload={loadLibrary} /> : null}
        {view === "discover" ? <section className="mx-auto max-w-4xl space-y-5"><div className="overflow-hidden rounded-3xl border border-[#29e68b]/15 bg-[radial-gradient(circle_at_80%_0%,rgba(41,230,139,0.13),transparent_40%),#0e1916] p-6 shadow-2xl sm:p-10"><Badge className="mb-5 border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]"><WandSparkles /> 自然语言选歌</Badge><h2 className="max-w-2xl text-2xl font-semibold leading-tight sm:text-4xl">你现在，想听什么感觉？</h2><p className="mt-3 text-sm leading-6 text-white/45">理解情绪、场景、强弱和排除项，并逐一评估全部已画像的喜欢歌曲。</p><form onSubmit={generateQueue} className="mt-7 space-y-4"><Textarea value={feeling} onChange={(event) => setFeeling(event.target.value)} rows={5} maxLength={1000} className="resize-none rounded-2xl border-white/10 bg-black/20 p-4 text-base text-white placeholder:text-white/25 focus-visible:border-[#29e68b]/50 focus-visible:ring-[#29e68b]/15" /><div className="flex flex-wrap gap-2">{examples.map((example) => <button type="button" key={example} onClick={() => setFeeling(example)} className="rounded-full border border-white/8 bg-white/[0.035] px-3 py-1.5 text-xs text-white/45 hover:bg-white/[0.07] hover:text-white/75">{example}</button>)}</div><Button type="submit" disabled={generating || !settings?.apiKeyConfigured} className="h-11 rounded-xl bg-[#29e68b] px-6 text-[#04110c] hover:bg-[#50efa1]">{generating ? <LoaderCircle className="animate-spin" /> : <Sparkles />}{generating ? "正在理解并全库匹配" : "生成临时队列"}</Button></form></div><ProfileCard settings={settings} job={job} progress={profileProgress} startProfiling={startProfiling} openSettings={() => setView("settings")} /></section> : null}
        {view === "queue" ? <QueueView queue={queue} busy={queueBusy} goDiscover={() => setView("discover")} sortQueue={sortQueue} removeCandidate={removeCandidate} findSimilar={findSimilar} saveOrder={saveOrder} refineQueue={refineQueue} playQueue={playQueue} /> : null}
        {view === "player" ? <PlayerView queue={queue} playback={playback} active={playerActive} busy={playerBusy} control={controlPlayback} openQueue={() => setView("queue")} /> : null}
        {view === "history" ? <HistoryView history={history} restorePlaylist={restorePlaylist} busy={queueBusy} /> : null}
        {view === "settings" ? <section className="mx-auto max-w-2xl rounded-2xl border border-white/[0.08] bg-[#0e1916] p-6 sm:p-8"><div className="flex items-center gap-3"><div className="grid size-11 place-items-center rounded-xl bg-[#7cc9ff]/10 text-[#7cc9ff]"><KeyRound /></div><div><h2 className="font-semibold">DeepSeek + 本地向量</h2><p className="text-sm text-white/40">DeepSeek 密钥仅保存在本机；Embedding 不调用云端</p></div></div><div className="mt-6 grid gap-3 sm:grid-cols-2"><Metric label="聊天模型" value={settings ? `${settings.chatProvider} · ${settings.chatModel}` : "—"} /><Metric label="本地 Embedding" value={settings ? `${settings.embeddingModel} · ${settings.embeddingDimensions} 维` : "—"} /></div><form onSubmit={saveKey} className="mt-6 space-y-3"><label className="text-sm text-white/65" htmlFor="api-key">DeepSeek API Key</label><Input id="api-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings?.apiKeyConfigured ? "已配置，输入新 Key 可替换" : "sk-…"} className="h-11 border-white/10 bg-black/20 text-white" /><Button disabled={savingKey || !apiKey.trim()} className="h-10 bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]">{savingKey ? <LoaderCircle className="animate-spin" /> : <KeyRound />}{savingKey ? "保存并验证" : "安全保存并测试"}</Button></form><p className="mt-5 text-xs leading-5 text-white/35">首次建立画像时会自动下载 BGE-M3，本地模型较大，请保持网络连接并预留磁盘空间。后续向量生成不产生 API 费用。</p></section> : null}
      </main>
    </SidebarInset><Toaster position="bottom-right" richColors />
  </SidebarProvider>;
}

function NavItem({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) { return <SidebarMenuItem><SidebarMenuButton isActive={active} tooltip={label} onClick={onClick} className="h-10 text-white/48 hover:bg-white/[0.07] hover:text-white data-[active=true]:bg-white/[0.08] data-[active=true]:text-[#75f0af]">{icon}<span>{label}</span></SidebarMenuButton></SidebarMenuItem>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-xs text-white/35">{label}</p><p className="mt-1 truncate text-sm font-medium text-white/85">{value}</p></div>; }

function PlayerView({ queue, playback, active, busy, control, openQueue }: { queue: TemporaryQueue | null; playback: PlaybackState | null; active: boolean; busy: boolean; control: (action: PlaybackAction) => Promise<void>; openQueue: () => void }) {
  if (!queue || !active) return <div className="grid min-h-[520px] place-items-center rounded-3xl border border-dashed border-white/10 bg-[#0e1916]"><div className="max-w-md px-6 text-center"><Play className="mx-auto size-12 text-[#75f0af]/60" /><h2 className="mt-5 text-xl font-semibold">播放器还没有接管歌单</h2><p className="mt-2 text-sm leading-6 text-white/40">先在临时队列中点击“交给 MoodMusic 播放”。声音仍由已登录的 QQ 音乐客户端输出。</p><Button onClick={openQueue} className="mt-6 bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]">打开临时队列</Button></div></div>;
  const normalize = (value: string | null) => (value ?? "").toLocaleLowerCase().replace(/\s/g, "");
  const detectedIndex = queue.songs.findIndex((song) => normalize(song.title) === normalize(playback?.title ?? null));
  const currentIndex = detectedIndex >= 0 ? detectedIndex : 0;
  const current = queue.songs[currentIndex];
  const duration = playback?.durationMs ?? current?.durationMs ?? null;
  const position = playback?.positionMs ?? 0;
  const progress = duration ? Math.min(100, Math.max(0, position / duration * 100)) : 0;
  const isPlaying = playback?.status === "playing";
  return <section className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
    <div className="flex min-h-[560px] flex-col justify-between overflow-hidden rounded-3xl border border-[#29e68b]/15 bg-[radial-gradient(circle_at_50%_10%,rgba(41,230,139,0.16),transparent_44%),#0e1916] p-6 sm:p-10">
      <div className="flex items-center justify-between"><Badge className="border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]">MoodMusic 托管中</Badge><span className="text-xs text-white/35">第 {currentIndex + 1} / {queue.songs.length} 首</span></div>
      <div className="py-10 text-center"><div className="mx-auto grid size-40 place-items-center rounded-[2.5rem] border border-white/10 bg-black/20 text-[#75f0af] shadow-[0_25px_80px_rgba(0,0,0,0.35)] sm:size-52"><Music2 className="size-20 opacity-70" /></div><h2 className="mt-8 text-2xl font-semibold sm:text-4xl">{playback?.title ?? current?.title ?? "正在连接 QQ 音乐"}</h2><p className="mt-3 text-base text-white/42">{playback?.artist ?? current?.artists.map((artist) => artist.name).join(" / ") ?? "—"}</p></div>
      <div><Progress value={progress} className="h-1.5 bg-white/[0.08]" /><div className="mt-2 flex justify-between text-xs text-white/30"><span>{formatDuration(position)}</span><span>{formatDuration(duration)}</span></div><div className="mt-6 flex items-center justify-center gap-4"><Button size="icon" variant="ghost" disabled={busy || currentIndex === 0} onClick={() => void control("previous")} title="上一首" className="size-12 rounded-full text-white/65 hover:bg-white/10 hover:text-white"><SkipBack className="size-6" /></Button><Button size="icon" disabled={busy} onClick={() => void control(isPlaying ? "pause" : "play")} title={isPlaying ? "暂停" : "继续"} className="size-16 rounded-full bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]">{busy ? <LoaderCircle className="size-7 animate-spin" /> : isPlaying ? <Pause className="size-7 fill-current" /> : <Play className="size-7 fill-current" />}</Button><Button size="icon" variant="ghost" disabled={busy || currentIndex >= queue.songs.length - 1} onClick={() => void control("next")} title="下一首" className="size-12 rounded-full text-white/65 hover:bg-white/10 hover:text-white"><SkipForward className="size-6" /></Button></div><p className="mt-6 text-center text-xs leading-5 text-white/30">请在这里切歌，MoodMusic 会直接点播目标歌曲，不经过 QQ 音乐原有队列。</p></div>
    </div>
    <div className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0e1916]"><div className="border-b border-white/[0.07] p-5"><h3 className="font-semibold">接下来播放</h3><p className="mt-1 text-xs text-white/35">{queue.name}</p></div><div className="max-h-[650px] overflow-y-auto">{queue.songs.map((song, index) => <div key={song.candidateId} className={`flex items-center gap-3 border-b border-white/[0.05] px-5 py-3 ${index === currentIndex ? "bg-[#29e68b]/10" : ""}`}><span className={`w-6 text-xs ${index === currentIndex ? "text-[#75f0af]" : "text-white/25"}`}>{index + 1}</span><div className="min-w-0"><p className={`truncate text-sm ${index === currentIndex ? "font-medium text-[#75f0af]" : "text-white/75"}`}>{song.title}</p><p className="truncate text-xs text-white/32">{song.artists.map((artist) => artist.name).join(" / ")}</p></div></div>)}</div></div>
  </section>;
}

function ProfileCard({ settings, job, progress, startProfiling, openSettings }: { settings: ModelSettings | null; job: Job | null; progress: number; startProfiling: () => void; openSettings: () => void }) {
  const running = !!job && ["queued", "running"].includes(job.status);
  return <div className="rounded-2xl border border-white/[0.08] bg-[#0e1916] p-5"><div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><h3 className="font-medium">歌曲多角度画像</h3><p className="mt-1 text-sm text-white/40">仅处理新增、元数据变化或模型版本变化的歌曲</p></div>{settings?.apiKeyConfigured ? <Button variant="outline" disabled={running} onClick={() => void startProfiling()} className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white">{running ? <LoaderCircle className="animate-spin" /> : <Database />}{running ? "画像进行中" : job?.status === "failed" ? "继续未完成画像" : job?.status === "succeeded" && job.failed ? `重试 ${job.failed} 首` : "更新全部画像"}</Button> : <Button variant="outline" onClick={openSettings}>先设置 API Key</Button>}</div>{job ? <div className="mt-5"><div className="mb-2 flex justify-between text-xs text-white/45"><span>{job.status === "succeeded" ? job.failed ? `主体完成，跳过 ${job.failed} 首` : "已完成" : job.status === "failed" ? "连接中断" : "正在批量处理"}</span><span>{job.completed + job.failed} / {job.total}</span></div><Progress value={progress} className="h-1.5 bg-white/[0.06]" />{job.lastError ? <p className={`mt-2 text-xs ${job.status === "succeeded" ? "text-amber-200" : "text-red-300"}`}>{job.lastError}</p> : null}</div> : null}</div>;
}

type QueueViewProps = {
  queue: TemporaryQueue | null;
  busy: boolean;
  goDiscover: () => void;
  sortQueue: (mode: "match" | "emotionCurve" | "random") => Promise<void>;
  removeCandidate: (candidateId: string) => Promise<void>;
  findSimilar: (candidateId: string) => Promise<void>;
  saveOrder: (candidateIds: string[]) => Promise<void>;
  refineQueue: (requirement: string) => Promise<void>;
  playQueue: () => Promise<void>;
};

function QueueView({ queue, busy, goDiscover, sortQueue, removeCandidate, findSimilar, saveOrder, refineQueue, playQueue }: QueueViewProps) {
  const [refinement, setRefinement] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(100);
  if (!queue) return <div className="grid min-h-[460px] place-items-center rounded-2xl border border-dashed border-white/10"><div className="text-center"><ListMusic className="mx-auto size-10 text-white/25" /><h2 className="mt-4 font-medium">还没有临时队列</h2><p className="mt-1 text-sm text-white/40">先描述一种想听的感觉。</p><Button onClick={goDiscover} className="mt-5 bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]">去 AI 选歌</Button></div></div>;
  const sortLabel = { match: "匹配度排序", emotionCurve: "情绪曲线", random: "随机排序", manual: "人工顺序", similar: "相似歌曲顺序", restored: "历史恢复" }[queue.sortMode] ?? queue.sortMode;
  const vocalLabels: Record<string, string> = { male_solo: "男声独唱", female_solo: "女声独唱", mixed_duet: "男女对唱", male_duet: "双男声", female_duet: "双女声", group: "组合", choir: "合唱团", instrumental: "纯音乐", other: "其他人声" };
  const languageLabels: Record<string, string> = { zh: "中文/普通话", yue: "粤语", en: "英语", ja: "日语", ko: "韩语", es: "西班牙语", fr: "法语", de: "德语", ru: "俄语", other: "其他语言" };
  const enforcedConstraints = [
    ...(queue.intent.requiredVocalModes?.length ? [`只保留：${queue.intent.requiredVocalModes.map((value) => vocalLabels[value] ?? value).join("、")}`] : []),
    ...(queue.intent.excludedVocalModes?.length ? [`排除：${queue.intent.excludedVocalModes.map((value) => vocalLabels[value] ?? value).join("、")}`] : []),
    ...(queue.intent.allowedLanguages?.length ? [`语言：${queue.intent.allowedLanguages.map((value) => languageLabels[value] ?? value).join("、")}`] : []),
    ...(queue.intent.excludedLanguages?.length ? [`排除语言：${queue.intent.excludedLanguages.map((value) => languageLabels[value] ?? value).join("、")}`] : []),
    ...(queue.intent.instrumentalAllowed === false ? ["排除纯音乐"] : []),
    ...(queue.intent.maxEnergy != null ? [`最高能量：${Math.round(queue.intent.maxEnergy * 100)}%`] : []),
  ];
  const dropOn = (targetId: string) => {
    if (!dragging || dragging === targetId || busy) return;
    const ids = queue.songs.map((song) => song.candidateId);
    const from = ids.indexOf(dragging); const to = ids.indexOf(targetId);
    ids.splice(to, 0, ids.splice(from, 1)[0]); setDragging(null); void saveOrder(ids);
  };
  return <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0e1916]">
    <div className="border-b border-white/[0.07] p-5 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"><div><Badge className="border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]">临时队列 · {sortLabel}</Badge><h2 className="mt-3 text-xl font-semibold">{queue.name}</h2><p className="mt-2 text-sm text-white/42">已评估 {queue.evaluatedCount} 首 · 当前 {queue.matchedCount} 首 · 阈值 {(queue.intent.threshold * 100).toFixed(0)}%</p>{queue.randomSeed !== null ? <p className="mt-1 text-xs text-white/30">随机种子：{queue.randomSeed}</p> : null}{queue.intent.exclusions.length ? <p className="mt-2 text-xs text-white/35">排除要求：{queue.intent.exclusions.join("、")}</p> : null}{enforcedConstraints.length ? <div className="mt-2 flex flex-wrap gap-1.5">{enforcedConstraints.map((constraint) => <Badge key={constraint} variant="outline" className="border-[#29e68b]/20 bg-[#29e68b]/5 text-[#75f0af]">已执行 · {constraint}</Badge>)}</div> : null}</div><Button disabled={busy || queue.songs.length === 0} onClick={() => void playQueue()} title="由 MoodMusic 托管歌单顺序并通过本机 QQ 音乐输出" className="bg-[#29e68b] text-[#04110c]"><Play />{busy ? "正在连接 QQ 音乐" : "交给 MoodMusic 播放"}</Button></div>
      <div className="mt-5 flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void sortQueue("match")} className="border-white/10 bg-white/[0.04] text-white"><GitCompareArrows />匹配度</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void sortQueue("emotionCurve")} className="border-white/10 bg-white/[0.04] text-white"><Waves />情绪曲线</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void sortQueue("random")} className="border-white/10 bg-white/[0.04] text-white"><Shuffle />随机</Button>{busy ? <span className="flex items-center gap-2 px-2 text-xs text-white/40"><LoaderCircle className="size-4 animate-spin" />正在保存新快照</span> : null}</div>
      <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); const value = refinement.trim(); if (value.length < 2) return; void refineQueue(value).then(() => setRefinement("")); }}><Input value={refinement} onChange={(event) => setRefinement(event.target.value)} placeholder="继续要求，例如：再少一点人声，前半段更轻快" className="border-white/10 bg-black/20 text-white" /><Button disabled={busy || refinement.trim().length < 2} className="bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"><Sparkles />追加要求</Button></form>
    </div>
    <Table><TableHeader><TableRow className="border-white/[0.07] hover:bg-transparent"><TableHead className="w-14 pl-4 text-white/35">#</TableHead><TableHead className="text-white/35">歌曲</TableHead><TableHead className="hidden text-white/35 md:table-cell">匹配构成</TableHead><TableHead className="w-20 text-right text-white/35">匹配度</TableHead><TableHead className="w-28 pr-4 text-right text-white/35">操作</TableHead></TableRow></TableHeader><TableBody>{queue.songs.slice(0, visibleCount).map((song, index) => <TableRow key={song.candidateId} draggable={!busy} onDragStart={() => setDragging(song.candidateId)} onDragOver={(event) => event.preventDefault()} onDrop={() => dropOn(song.candidateId)} className={`border-white/[0.055] hover:bg-white/[0.035] ${dragging === song.candidateId ? "opacity-40" : ""}`}><TableCell className="pl-4 text-white/25"><span className="flex items-center gap-1"><GripVertical className="size-3 cursor-grab" />{index + 1}</span></TableCell><TableCell><p className="font-medium text-white/90">{song.title}</p><p className="text-sm text-white/38">{song.artists.map((artist) => artist.name).join(" / ")}</p></TableCell><TableCell className="hidden text-xs text-white/38 md:table-cell">语义 {(song.semanticScore * 100).toFixed(0)}% · 特征 {(song.featureScore * 100).toFixed(0)}%</TableCell><TableCell className="text-right font-medium text-[#75f0af]">{(song.score * 100).toFixed(0)}%</TableCell><TableCell className="pr-4"><div className="flex justify-end gap-1"><Button size="icon" variant="ghost" disabled={busy} title="以这首歌为基准找相似" onClick={() => void findSimilar(song.candidateId)} className="size-8 text-white/45 hover:text-[#75f0af]"><GitCompareArrows /></Button><Button size="icon" variant="ghost" disabled={busy} title="从当前会话移除" onClick={() => void removeCandidate(song.candidateId)} className="size-8 text-white/45 hover:text-red-300"><Trash2 /></Button></div></TableCell></TableRow>)}</TableBody></Table>
    {visibleCount < queue.songs.length ? <div className="border-t border-white/[0.07] p-4 text-center"><Button variant="ghost" onClick={() => setVisibleCount((value) => value + 100)} className="text-white/55">再显示 100 首</Button></div> : null}
    {queue.songs.length === 0 ? <div className="p-12 text-center text-sm text-white/40">当前要求下没有歌曲通过筛选，可以追加更宽松的要求或重新搜索。</div> : null}
  </section>;
}

function HistoryView({ history, restorePlaylist, busy }: { history: PlaylistHistoryPage | null; restorePlaylist: (playlistId: string) => Promise<void>; busy: boolean }) {
  const labels: Record<string, string> = { match: "匹配度", emotionCurve: "情绪曲线", random: "随机", manual: "人工调整", similar: "找相似", restored: "历史恢复" };
  if (!history) return <div className="space-y-3">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-24 bg-white/[0.05]" />)}</div>;
  return <section className="space-y-3"><div className="mb-5"><h2 className="font-medium">共 {history.total} 个可回放快照</h2><p className="mt-1 text-sm text-white/40">每次排序、删除、拖动和追加要求都会保留旧版本。</p></div>{history.playlists.map((playlist) => <button key={playlist.playlistId} disabled={busy} onClick={() => void restorePlaylist(playlist.playlistId)} className="flex w-full flex-col gap-3 rounded-2xl border border-white/[0.08] bg-[#0e1916] p-5 text-left transition hover:border-[#29e68b]/25 hover:bg-[#10201b] sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex items-center gap-2"><Badge className="border-white/10 bg-white/[0.04] text-white/55">{labels[playlist.sortMode] ?? playlist.sortMode}</Badge><span className="text-xs text-white/30">{playlist.songCount} 首</span></div><p className="mt-2 truncate font-medium text-white/90">{playlist.name}</p><p className="mt-1 truncate text-sm text-white/35">{playlist.description}</p></div><div className="shrink-0 text-xs text-white/30">{new Date(playlist.createdAt).toLocaleString("zh-CN")}</div></button>)}</section>;
}

type LibraryViewProps = { library: LibraryPage | null; loading: boolean; error: string | null; page: number; totalPages: number; query: string; searchDraft: string; setSearchDraft: (value: string) => void; submitSearch: (event: FormEvent<HTMLFormElement>) => void; setPage: (page: number) => void; reload: () => Promise<void> };
function LibraryView({ library, loading, error, page, totalPages, query, searchDraft, setSearchDraft, submitSearch, setPage, reload }: LibraryViewProps) {
  const pageOptions = useMemo(() => [...new Set([0, page - 1, page, page + 1, totalPages - 1])].filter((item) => item >= 0 && item < totalPages).sort((a, b) => a - b), [page, totalPages]);
  return <><section className="mb-6 grid gap-3 sm:grid-cols-3"><div className="metric-card"><LibraryBig className="size-4 text-[#62eca4]" /><div><p className="metric-value">{library?.total.toLocaleString("zh-CN") ?? "—"}</p><p className="metric-label">{query ? "搜索结果" : "喜欢的歌曲"}</p></div></div><div className="metric-card"><Database className="size-4 text-[#7cc9ff]" /><div><p className="metric-value">PostgreSQL + pgvector</p><p className="metric-label">本地曲库与语义向量</p></div></div><div className="metric-card"><Clock3 className="size-4 text-[#d2aeff]" /><div><p className="metric-value">增量同步</p><p className="metric-label">只处理发生变化的歌曲</p></div></div></section><section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0e1916]"><div className="flex flex-col gap-4 border-b border-white/[0.07] p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"><div><h2 className="font-medium">曲库</h2><p className="mt-1 text-sm text-white/40">每页显示 {PAGE_SIZE} 首</p></div><form onSubmit={submitSearch} className="flex w-full gap-2 sm:max-w-md"><div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/30" /><Input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="搜索歌曲、歌手或专辑" className="h-10 border-white/[0.08] bg-white/[0.04] pl-9 text-white" /></div><Button variant="outline" className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white">搜索</Button></form></div>{loading ? <div className="space-y-3 p-5">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-12 bg-white/[0.05]" />)}</div> : error ? <div className="grid min-h-[380px] place-items-center text-center"><div><WifiOff className="mx-auto text-red-300" /><p className="mt-3 text-white/70">{error}</p><Button onClick={() => void reload()} variant="outline" className="mt-4">重新连接</Button></div></div> : library?.songs.length ? <><Table><TableHeader><TableRow className="border-white/[0.07] hover:bg-transparent"><TableHead className="w-14 pl-5 text-white/35">#</TableHead><TableHead className="text-white/35">歌曲</TableHead><TableHead className="hidden text-white/35 md:table-cell">专辑</TableHead><TableHead className="w-24 pr-5 text-right text-white/35">时长</TableHead></TableRow></TableHeader><TableBody>{library.songs.map((song, index) => <TableRow key={song.id} className="border-white/[0.055] hover:bg-white/[0.035]"><TableCell className="pl-5 text-white/25">{page * PAGE_SIZE + index + 1}</TableCell><TableCell><p className="font-medium text-white/90">{song.title}</p><p className="text-sm text-white/38">{song.artists.map((artist) => artist.name).join(" / ")}</p></TableCell><TableCell className="hidden max-w-[22rem] truncate text-white/40 md:table-cell">{song.album ?? "—"}</TableCell><TableCell className="pr-5 text-right text-white/35">{formatDuration(song.durationMs)}</TableCell></TableRow>)}</TableBody></Table><div className="flex items-center justify-between border-t border-white/[0.07] p-4"><p className="text-sm text-white/35">第 {page + 1} / {totalPages} 页</p><div className="flex gap-1">{pageOptions.map((option) => <Button key={option} size="sm" variant={option === page ? "default" : "ghost"} onClick={() => setPage(option)} className={option === page ? "bg-[#29e68b] text-[#04110c]" : "text-white/50"}>{option + 1}</Button>)}</div></div></> : <div className="grid min-h-[380px] place-items-center text-sm text-white/40">{query ? "没有找到匹配歌曲" : "曲库还是空的，请先同步 QQ 音乐"}</div>}</section></>;
}
