"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  History,
  LibraryBig,
  ListMusic,
  LoaderCircle,
  Music2,
  Play,
  RefreshCw,
  Settings2,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import {
  DEMO_BUILD_ENABLED,
  demoLibraryPage,
  demoSettings,
  isDemoMode,
} from "@/lib/demo-api";
import { musicApi, PAGE_SIZE } from "@/lib/music-api";
import type {
  LibrarySongPage as LibraryPage,
  ModelSettings,
  JobStatus as Job,
  TemporaryQueue,
  PlaylistHistoryPage,
  PCPlaybackState as PlaybackState,
  PCPlaybackActionInput,
} from "@/lib/api-types";
import { PlayerView } from "@/components/moodmusic/player-view";
import { ProfileCard } from "@/components/moodmusic/profile-card";
import { QueueView } from "@/components/moodmusic/queue-view";
import { HistoryView } from "@/components/moodmusic/history-view";
import { LibraryView } from "@/components/moodmusic/library-view";
import { SettingsView } from "@/components/moodmusic/settings-view";
type View =
  | "library"
  | "discover"
  | "queue"
  | "player"
  | "history"
  | "settings";
type PlaybackAction = PCPlaybackActionInput["action"];

const examples = [
  "凌晨开车，有一点孤独，但不要太悲伤",
  "周五下班路上，轻快松弛，别太吵",
  "专注写代码，有流动感，尽量少人声",
];
const subscribeDemoMode = () => () => undefined;

export default function Home() {
  const demoMode = useSyncExternalStore(
    subscribeDemoMode,
    isDemoMode,
    isDemoMode,
  );
  const [view, setView] = useState<View>("library");
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [library, setLibrary] = useState<LibraryPage | null>(
    DEMO_BUILD_ENABLED ? demoLibraryPage : null,
  );
  const [loading, setLoading] = useState(!DEMO_BUILD_ENABLED);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const libraryRequest = useRef<AbortController | null>(null);
  const [libraryRevision, setLibraryRevision] = useState(0);
  const [jobError, setJobError] = useState<string | null>(null);
  const [settings, setSettings] = useState<ModelSettings | null>(
    DEMO_BUILD_ENABLED ? demoSettings : null,
  );
  const [job, setJob] = useState<Job | null>(null);
  const [feeling, setFeeling] = useState(examples[0]);
  const [generating, setGenerating] = useState(false);
  const [queue, setQueue] = useState<TemporaryQueue | null>(null);
  const [queueBusy, setQueueBusy] = useState(false);
  const [history, setHistory] = useState<PlaylistHistoryPage | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [playingQueue, setPlayingQueue] = useState<TemporaryQueue | null>(null);
  const [playerActive, setPlayerActive] = useState(false);
  const [playerBusy, setPlayerBusy] = useState(false);
  const [playback, setPlayback] = useState<PlaybackState | null>(null);

  const loadLibrary = useCallback(async () => {
    setLoading(true);
    setError(null);
    libraryRequest.current?.abort();
    const request = new AbortController();
    libraryRequest.current = request;
    try {
      const result = await musicApi.library(page, query, request.signal);
      if (!request.signal.aborted) setLibrary(result);
    } catch (requestError) {
      if (!request.signal.aborted)
        setError(
          requestError instanceof Error
            ? requestError.message
            : "无法读取本地曲库",
        );
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }, [page, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadLibrary(), 0);
    return () => {
      window.clearTimeout(timer);
      libraryRequest.current?.abort();
    };
  }, [loadLibrary, libraryRevision]);
  useEffect(() => {
    void musicApi
      .settings()
      .then(setSettings)
      .catch((error) =>
        toast.error(error instanceof Error ? error.message : "无法读取设置"),
      );
  }, []);
  useEffect(() => {
    if (view !== "history") return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setHistoryLoading(true);
      setHistoryError(null);
      void musicApi
        .history(controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setHistory(result);
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setHistoryError(
              error instanceof Error ? error.message : "无法读取队列历史",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setHistoryLoading(false);
        });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [view, historyRevision]);
  const jobId = job?.jobId;
  const jobStatus = job?.status;
  useEffect(() => {
    if (!jobId || !["queued", "running"].includes(jobStatus ?? "")) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await musicApi.job(jobId);
        if (cancelled) return;
        setJob(next);
        setJobError(null);
        if (next.status === "succeeded" && next.failed)
          toast.warning(`主体画像已完成，${next.failed} 首可稍后重试`);
        else if (next.status === "succeeded")
          toast.success("全部待处理歌曲已完成画像");
        if (next.status === "failed")
          toast.error(next.lastError ?? "画像任务失败");
      } catch (error) {
        if (!cancelled)
          setJobError(
            error instanceof Error
              ? error.message
              : "无法读取任务进度，连接恢复后会重试",
          );
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 1500);
      }
    };
    timer = setTimeout(() => void poll(), 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, jobStatus]);
  const playingPlaylistId = playingQueue?.playlistId;
  useEffect(() => {
    if (!playerActive || !playingPlaylistId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await musicApi.playback(controller.signal);
        if (!cancelled) setPlayback(result);
      } catch (error) {
        if (!cancelled)
          setPlayback((current) =>
            current
              ? {
                  ...current,
                  status: "unavailable",
                  positionMs: null,
                  durationMs: null,
                  canPlay: false,
                  canPause: false,
                  canNext: false,
                  canPrevious: false,
                  message:
                    error instanceof Error
                      ? error.message
                      : "播放器状态读取失败，连接恢复后将自动重试。",
                }
              : current,
          );
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 2000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [playerActive, playingPlaylistId]);

  const refreshJob = useCallback(async () => {
    try {
      const latest = await musicApi.latestJob();
      setJob(latest);
      setJobError(null);
    } catch (error) {
      setJobError(error instanceof Error ? error.message : "无法读取最新任务");
    }
  }, []);
  useEffect(() => {
    let cancelled = false;
    void musicApi
      .latestJob()
      .then((latest) => {
        if (!cancelled) setJob((current) => current ?? latest);
      })
      .catch((error) => {
        if (!cancelled)
          setJobError(
            error instanceof Error ? error.message : "无法读取最新任务",
          );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalPages = Math.max(1, Math.ceil((library?.total ?? 0) / PAGE_SIZE));
  const profileProgress = job?.total
    ? Math.round(((job.completed + job.failed) / job.total) * 100)
    : job?.status === "succeeded"
      ? 100
      : 0;
  const title = {
    library: "我的喜欢",
    discover: "AI 选歌",
    queue: "临时队列",
    player: "播放器",
    history: "队列历史",
    settings: "首次配置与设置",
  }[view];
  const subtitle = {
    library: "QQ 音乐收藏的本地镜像",
    discover: "描述一种感觉，从全部喜欢中找到它",
    queue: "排序、删减、拖动或继续描述",
    player: "由 MoodMusic 掌握播放顺序，QQ 音乐负责声音输出",
    history: "恢复每一次筛选、排序和人工调整快照",
    settings: "密钥只保存在本机 Windows 凭据存储",
  }[view];

  async function syncLibrary() {
    setSyncing(true);
    try {
      const result = await musicApi.sync();
      setPage(0);
      setLibraryRevision((value) => value + 1);
      toast.success(
        `同步完成，共 ${result.uniqueCount.toLocaleString("zh-CN")} 首歌曲`,
      );
    } catch (syncError) {
      toast.error(syncError instanceof Error ? syncError.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  }

  async function startProfiling() {
    try {
      const retrying =
        job?.status === "failed" ||
        (job?.status === "succeeded" && job.failed > 0);
      const result = retrying
        ? await musicApi.retryJob(job!.jobId)
        : await musicApi.startProfiling();
      setJob(result);
      setJobError(null);
      toast.success(
        retrying
          ? `将从 ${result.completed} / ${result.total} 继续处理`
          : result.total
            ? `已开始为 ${result.total} 首歌曲建立画像`
            : "画像已经是最新状态",
      );
    } catch (profileError) {
      toast.error(
        profileError instanceof Error
          ? profileError.message
          : "无法创建画像任务",
      );
    }
  }

  async function generateQueue(event: FormEvent) {
    event.preventDefault();
    if (feeling.trim().length < 2) return;
    setGenerating(true);
    try {
      const result = await musicApi.generate(feeling.trim());
      setQueue(result);
      setView("queue");
      toast.success(
        `已从 ${result.evaluatedCount} 首画像歌曲中选出 ${result.matchedCount} 首`,
      );
    } catch (searchError) {
      toast.error(
        searchError instanceof Error ? searchError.message : "AI 选歌失败",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function updateQueue(
    operation: () => Promise<TemporaryQueue>,
    success: string,
  ) {
    setQueueBusy(true);
    try {
      const result = await operation();
      setQueue(result);
      setView("queue");
      toast.success(success);
      return true;
    } catch (queueError) {
      toast.error(
        queueError instanceof Error ? queueError.message : "队列更新失败",
      );
      return false;
    } finally {
      setQueueBusy(false);
    }
  }

  async function sortQueue(mode: "match" | "emotionCurve" | "random") {
    if (!queue) return;
    await updateQueue(
      () => musicApi.sort(queue.sessionId, mode),
      mode === "match"
        ? "已恢复匹配度排序"
        : mode === "random"
          ? "已生成可复现随机顺序"
          : "已生成平滑情绪曲线",
    );
  }

  async function removeCandidate(candidateId: string) {
    if (queue)
      await updateQueue(
        () => musicApi.remove(queue.sessionId, candidateId),
        "已从当前会话移除歌曲",
      );
  }
  async function findSimilar(candidateId: string) {
    if (queue)
      await updateQueue(
        () => musicApi.similar(queue.sessionId, candidateId),
        "已按与该歌曲的相似度重新排列",
      );
  }
  async function saveOrder(candidateIds: string[]) {
    if (queue)
      await updateQueue(
        () => musicApi.order(queue.sessionId, candidateIds),
        "已保存人工顺序",
      );
  }
  async function refineQueue(requirement: string) {
    if (!queue) return false;
    return updateQueue(
      () => musicApi.refine(queue.sessionId, requirement),
      "已按追加要求重新筛选全部画像歌曲",
    );
  }
  async function restorePlaylist(playlistId: string) {
    await updateQueue(
      () => musicApi.restore(playlistId),
      "已把历史快照恢复为可编辑的当前队列",
    );
  }

  async function playQueue() {
    if (!queue) return;
    setQueueBusy(true);
    try {
      const selected = queue;
      const result = await musicApi.playQueue(selected.playlistId);
      setPlayingQueue(selected);
      setPlayerActive(true);
      setPlayback({
        status: result.observed ? "playing" : "unavailable",
        title: result.title,
        artist: result.artist,
        album: null,
        positionMs: 0,
        durationMs: null,
        canPlay: true,
        canPause: true,
        canNext: true,
        canPrevious: false,
        message: result.message,
      });
      setView("player");
      if (result.observed) toast.success(`QQ 音乐正在播放：${result.title}`);
      else toast.warning(result.message);
    } catch (playbackError) {
      toast.error(
        playbackError instanceof Error
          ? playbackError.message
          : "无法在 QQ 音乐中开始播放",
      );
    } finally {
      setQueueBusy(false);
    }
  }

  async function controlPlayback(action: PlaybackAction) {
    setPlayerBusy(true);
    try {
      const result = await musicApi.control(action);
      setPlayback((current) => ({
        canPlay: current?.canPlay ?? true,
        canPause: current?.canPause ?? true,
        canNext: current?.canNext ?? true,
        canPrevious: current?.canPrevious ?? true,
        status: result.playbackStatus,
        title: result.title ?? current?.title ?? null,
        artist: result.artist ?? current?.artist ?? null,
        album: current?.album ?? null,
        positionMs:
          action === "next" || action === "previous"
            ? 0
            : (current?.positionMs ?? null),
        durationMs:
          action === "next" || action === "previous"
            ? null
            : (current?.durationMs ?? null),
        message: result.message,
      }));
      if (!result.accepted) toast.info(result.message);
    } catch (controlError) {
      toast.error(
        controlError instanceof Error ? controlError.message : "播放器控制失败",
      );
    } finally {
      setPlayerBusy(false);
    }
  }

  return (
    <SidebarProvider
      style={{ "--sidebar-width": "15rem" } as React.CSSProperties}
      className="bg-[#07100e]"
    >
      <Sidebar collapsible="icon" className="border-r-0 bg-[#07100e]">
        <SidebarHeader className="px-3 py-5">
          <div className="flex items-center gap-3 px-1">
            <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#29e68b] text-[#04110c] shadow-[0_0_28px_rgba(41,230,139,0.25)]">
              <Music2 className="size-5" />
            </div>
            <div className="min-w-0 group-data-[collapsible=icon]:hidden">
              <p className="truncate text-[15px] font-semibold text-white">
                MoodMusic
              </p>
              <p className="truncate text-xs text-white/40">我的音乐工作台</p>
            </div>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="text-white/35">
              音乐
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <NavItem
                  icon={<LibraryBig />}
                  label="我的喜欢"
                  active={view === "library"}
                  onClick={() => setView("library")}
                />
                <NavItem
                  icon={<Sparkles />}
                  label="AI 选歌"
                  active={view === "discover"}
                  onClick={() => setView("discover")}
                />
                <NavItem
                  icon={<ListMusic />}
                  label="临时队列"
                  active={view === "queue"}
                  onClick={() => setView("queue")}
                />
                <NavItem
                  icon={<Play />}
                  label="播放器"
                  active={view === "player"}
                  onClick={() => setView("player")}
                />
                <NavItem
                  icon={<History />}
                  label="队列历史"
                  active={view === "history"}
                  onClick={() => setView("history")}
                />
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="px-3 pb-4">
          <SidebarMenu>
            <NavItem
              icon={<Settings2 />}
              label="连接与模型设置"
              active={view === "settings"}
              onClick={() => setView("settings")}
            />
          </SidebarMenu>
          <div className="mt-2 flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2.5 text-xs text-white/45 group-data-[collapsible=icon]:hidden">
            <span className="size-1.5 rounded-full bg-[#29e68b]" />
            曲库与密钥保存在本机
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="min-w-0 bg-[#0b1412] text-[#eff8f3]">
        <header className="sticky top-0 z-10 flex min-h-20 items-center justify-between border-b border-white/[0.07] bg-[#0b1412]/90 px-4 backdrop-blur-xl sm:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <SidebarTrigger className="text-white/60 hover:bg-white/[0.06] hover:text-white" />
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold sm:text-xl">{title}</h1>
                {demoMode ? (
                  <Badge className="border-amber-300/20 bg-amber-300/10 text-amber-200">
                    演示模式
                  </Badge>
                ) : null}
              </div>
              <p className="mt-0.5 hidden text-sm text-white/42 sm:block">
                {demoMode
                  ? "使用虚构示例数据，不会连接 QQ 音乐或外部模型"
                  : subtitle}
              </p>
            </div>
          </div>
          {view === "library" ? (
            <Button
              onClick={() => void syncLibrary()}
              disabled={syncing}
              className="h-10 rounded-xl bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"
            >
              <RefreshCw className={syncing ? "animate-spin" : ""} />
              {syncing ? "正在同步" : demoMode ? "模拟同步" : "同步 QQ 音乐"}
            </Button>
          ) : null}
        </header>
        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
          {view === "library" ? (
            <LibraryView
              library={library}
              loading={loading}
              error={error}
              page={page}
              totalPages={totalPages}
              query={query}
              searchDraft={searchDraft}
              setSearchDraft={setSearchDraft}
              submitSearch={(event) => {
                event.preventDefault();
                setPage(0);
                setQuery(searchDraft.trim());
              }}
              setPage={setPage}
              reload={loadLibrary}
            />
          ) : null}
          {view === "discover" ? (
            <section className="mx-auto max-w-4xl space-y-5">
              <div className="overflow-hidden rounded-3xl border border-[#29e68b]/15 bg-[radial-gradient(circle_at_80%_0%,rgba(41,230,139,0.13),transparent_40%),#0e1916] p-6 shadow-2xl sm:p-10">
                <Badge className="mb-5 border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]">
                  <WandSparkles /> 自然语言选歌
                </Badge>
                <h2 className="max-w-2xl text-2xl font-semibold leading-tight sm:text-4xl">
                  你现在，想听什么感觉？
                </h2>
                <p className="mt-3 text-sm leading-6 text-white/45">
                  理解情绪、场景、强弱和排除项，并逐一评估全部已画像的喜欢歌曲。
                </p>
                <form onSubmit={generateQueue} className="mt-7 space-y-4">
                  <Textarea
                    value={feeling}
                    onChange={(event) => setFeeling(event.target.value)}
                    rows={5}
                    maxLength={1000}
                    className="resize-none rounded-2xl border-white/10 bg-black/20 p-4 text-base text-white placeholder:text-white/25 focus-visible:border-[#29e68b]/50 focus-visible:ring-[#29e68b]/15"
                  />
                  <div className="flex flex-wrap gap-2">
                    {examples.map((example) => (
                      <button
                        type="button"
                        key={example}
                        onClick={() => setFeeling(example)}
                        className="rounded-full border border-white/8 bg-white/[0.035] px-3 py-1.5 text-xs text-white/45 hover:bg-white/[0.07] hover:text-white/75"
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                  <Button
                    type="submit"
                    disabled={generating || !settings?.apiKeyConfigured}
                    className="h-11 rounded-xl bg-[#29e68b] px-6 text-[#04110c] hover:bg-[#50efa1]"
                  >
                    {generating ? (
                      <LoaderCircle className="animate-spin" />
                    ) : (
                      <Sparkles />
                    )}
                    {generating ? "正在理解并全库匹配" : "生成临时队列"}
                  </Button>
                </form>
              </div>
              <ProfileCard
                settings={settings}
                job={job}
                progress={profileProgress}
                error={jobError}
                refreshJob={refreshJob}
                startProfiling={startProfiling}
                openSettings={() => setView("settings")}
              />
            </section>
          ) : null}
          {view === "queue" ? (
            <QueueView
              queue={queue}
              busy={queueBusy}
              goDiscover={() => setView("discover")}
              sortQueue={sortQueue}
              removeCandidate={removeCandidate}
              findSimilar={findSimilar}
              saveOrder={saveOrder}
              refineQueue={refineQueue}
              playQueue={playQueue}
            />
          ) : null}
          {view === "player" ? (
            <PlayerView
              queue={playingQueue}
              playback={playback}
              active={playerActive}
              busy={playerBusy}
              control={controlPlayback}
              openQueue={() => setView("queue")}
            />
          ) : null}
          {view === "history" ? (
            <HistoryView
              history={history}
              error={historyError}
              loading={historyLoading}
              retry={() => setHistoryRevision((value) => value + 1)}
              restorePlaylist={restorePlaylist}
              busy={queueBusy}
            />
          ) : null}
          {view === "settings" ? (
            <SettingsView
              settings={settings}
              onSettings={setSettings}
              syncing={syncing}
              syncLibrary={syncLibrary}
              jobError={jobError}
              refreshJob={refreshJob}
              job={job}
              progress={profileProgress}
              startProfiling={startProfiling}
              goDiscover={() => setView("discover")}
            />
          ) : null}
        </main>
      </SidebarInset>
      <Toaster position="bottom-right" richColors />
    </SidebarProvider>
  );
}

function NavItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        isActive={active}
        tooltip={label}
        onClick={onClick}
        className="h-10 text-white/48 hover:bg-white/[0.07] hover:text-white data-[active=true]:bg-white/[0.08] data-[active=true]:text-[#75f0af]"
      >
        {icon}
        <span>{label}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
