"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Clock3,
  Compass,
  Database,
  LibraryBig,
  ListMusic,
  Music2,
  RefreshCw,
  Search,
  Settings2,
  Sparkles,
  WifiOff,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
} from "@/components/ui/pagination";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Toaster } from "@/components/ui/sonner";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PAGE_SIZE = 50;

type Artist = { name: string };

type LibrarySong = {
  id: string;
  sourceTrackId: string;
  title: string;
  artists: Artist[];
  album: string | null;
  durationMs: number | null;
  firstSeenAt: string;
  lastSeenAt: string;
};

type LibraryPage = {
  page: number;
  pageSize: number;
  total: number;
  songs: LibrarySong[];
};

type SyncResult = {
  status: string;
  pagesFetched: number;
  reportedTotal: number;
  uniqueCount: number;
  insertedCount: number;
  updatedCount: number;
  deactivatedCount: number;
};

async function requestLibrary(page: number, query: string) {
  const params = new URLSearchParams({ page: String(page), pageSize: String(PAGE_SIZE) });
  if (query) params.set("q", query);
  const response = await fetch(`${API_URL}/api/v1/library/songs?${params}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error("本地音乐服务暂时不可用");
  return (await response.json()) as LibraryPage;
}

function formatDuration(durationMs: number | null) {
  if (!durationMs) return "—";
  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function pageNumbers(current: number, total: number) {
  const candidates = new Set([0, total - 1, current - 1, current, current + 1]);
  return [...candidates].filter((page) => page >= 0 && page < total).sort((a, b) => a - b);
}

export default function Home() {
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [library, setLibrary] = useState<LibraryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<SyncResult | null>(null);

  const loadLibrary = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      setLibrary(await requestLibrary(page, query));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "无法读取本地曲库");
    } finally {
      setLoading(false);
    }
  }, [page, query]);

  useEffect(() => {
    void loadLibrary();
  }, [loadLibrary]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();

    void Promise.resolve(
      context.registerTool(
        {
          name: "search_liked_library",
          title: "搜索我的喜欢",
          description: "按歌曲名、歌手或专辑搜索当前页面连接的本地 QQ 音乐喜欢曲库。",
          inputSchema: {
            type: "object",
            properties: {
              query: { type: "string", maxLength: 100 },
            },
            required: ["query"],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: true, untrustedContentHint: true },
          async execute(input) {
            const candidate = input as { query?: unknown };
            if (typeof candidate.query !== "string" || candidate.query.length > 100) {
              throw new Error("query 必须是不超过 100 个字符的字符串");
            }
            const nextQuery = candidate.query.trim();
            setLoading(true);
            setError(null);
            setSearchDraft(nextQuery);
            setQuery(nextQuery);
            setPage(0);
            try {
              const result = await requestLibrary(0, nextQuery);
              setLibrary(result);
              return { query: nextQuery, total: result.total, visibleCount: result.songs.length };
            } finally {
              setLoading(false);
            }
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch(() => undefined);

    return () => lifecycle.abort();
  }, []);

  const totalPages = Math.max(1, Math.ceil((library?.total ?? 0) / PAGE_SIZE));
  const pages = useMemo(() => pageNumbers(page, totalPages), [page, totalPages]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(0);
    setQuery(searchDraft.trim());
  }

  async function syncLibrary() {
    setSyncing(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/library/sync`, { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(body?.detail?.message ?? "同步失败，请检查 QQ 音乐登录状态");
      }
      const result = (await response.json()) as SyncResult;
      setLastSync(result);
      setPage(0);
      await loadLibrary();
      toast.success(`同步完成，共 ${result.uniqueCount.toLocaleString("zh-CN")} 首歌曲`);
    } catch (syncError) {
      toast.error(syncError instanceof Error ? syncError.message : "同步失败");
    } finally {
      setSyncing(false);
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
              <p className="truncate text-[15px] font-semibold tracking-[-0.02em] text-white">
                MoodMusic
              </p>
              <p className="truncate text-xs text-white/40">我的音乐工作台</p>
            </div>
          </div>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="text-white/35">音乐</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive
                    tooltip="我的喜欢"
                    className="h-10 bg-white/[0.08] text-[#75f0af] hover:bg-white/[0.1] hover:text-[#75f0af] data-[active=true]:bg-white/[0.08] data-[active=true]:text-[#75f0af]"
                  >
                    <LibraryBig />
                    <span>我的喜欢</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton disabled tooltip="AI 选歌 · 即将开发" className="h-10 text-white/40">
                    <Sparkles />
                    <span>AI 选歌</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton disabled tooltip="播放队列 · 即将开发" className="h-10 text-white/40">
                    <ListMusic />
                    <span>播放队列</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarGroup>
            <SidebarGroupLabel className="text-white/35">发现</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton disabled tooltip="相似歌曲 · 即将开发" className="h-10 text-white/40">
                    <Compass />
                    <span>相似歌曲</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter className="px-3 pb-4">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton disabled tooltip="设置 · 即将开发" className="h-10 text-white/40">
                <Settings2 />
                <span>设置</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          <div className="mt-2 flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2.5 text-xs text-white/45 group-data-[collapsible=icon]:hidden">
            <span className="size-1.5 rounded-full bg-[#29e68b] shadow-[0_0_10px_#29e68b]" />
            数据仅保存在本机
          </div>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0 bg-[#0b1412] text-[#eff8f3]">
        <header className="sticky top-0 z-10 flex min-h-20 items-center justify-between border-b border-white/[0.07] bg-[#0b1412]/90 px-4 backdrop-blur-xl sm:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <SidebarTrigger className="text-white/60 hover:bg-white/[0.06] hover:text-white" />
            <div>
              <h1 className="text-lg font-semibold tracking-[-0.02em] sm:text-xl">我的喜欢</h1>
              <p className="mt-0.5 hidden text-sm text-white/42 sm:block">
                QQ 音乐收藏的本地镜像
              </p>
            </div>
          </div>
          <Button
            onClick={() => void syncLibrary()}
            disabled={syncing}
            className="h-10 rounded-xl bg-[#29e68b] px-4 text-[#04110c] shadow-[0_8px_30px_rgba(41,230,139,0.13)] hover:bg-[#50efa1]"
          >
            <RefreshCw className={syncing ? "animate-spin" : ""} />
            {syncing ? "正在同步" : "同步 QQ 音乐"}
          </Button>
        </header>

        <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
          <section className="mb-6 grid gap-3 sm:grid-cols-3">
            <div className="metric-card">
              <LibraryBig className="size-4 text-[#62eca4]" />
              <div>
                <p className="metric-value">{library?.total.toLocaleString("zh-CN") ?? "—"}</p>
                <p className="metric-label">{query ? "搜索结果" : "喜欢的歌曲"}</p>
              </div>
            </div>
            <div className="metric-card">
              <Database className="size-4 text-[#7cc9ff]" />
              <div>
                <p className="metric-value">PostgreSQL</p>
                <p className="metric-label">本地曲库</p>
              </div>
            </div>
            <div className="metric-card">
              <Clock3 className="size-4 text-[#d2aeff]" />
              <div>
                <p className="metric-value">{lastSync ? `${lastSync.pagesFetched} 页` : "已连接"}</p>
                <p className="metric-label">{lastSync ? "刚刚完成同步" : "音乐服务状态"}</p>
              </div>
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0e1916] shadow-[0_24px_80px_rgba(0,0,0,0.18)]">
            <div className="flex flex-col gap-4 border-b border-white/[0.07] p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div>
                <h2 className="font-medium text-white">曲库</h2>
                <p className="mt-1 text-sm text-white/40">
                  {query ? `正在搜索“${query}”` : `每页显示 ${PAGE_SIZE} 首`}
                </p>
              </div>
              <form onSubmit={submitSearch} className="flex w-full gap-2 sm:max-w-md">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/30" />
                  <Input
                    value={searchDraft}
                    onChange={(event) => setSearchDraft(event.target.value)}
                    placeholder="搜索歌曲、歌手或专辑"
                    aria-label="搜索歌曲、歌手或专辑"
                    className="h-10 rounded-xl border-white/[0.08] bg-white/[0.04] pl-9 text-white shadow-none placeholder:text-white/28 focus-visible:border-[#29e68b]/50 focus-visible:ring-[#29e68b]/15"
                  />
                </div>
                <Button
                  type="submit"
                  variant="outline"
                  className="h-10 rounded-xl border-white/[0.09] bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white"
                >
                  搜索
                </Button>
              </form>
            </div>

            {loading ? (
              <div className="space-y-px p-2" aria-label="正在读取曲库">
                {Array.from({ length: 8 }, (_, index) => (
                  <div key={index} className="flex items-center gap-4 px-3 py-3">
                    <Skeleton className="size-10 rounded-lg bg-white/[0.06]" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3.5 w-1/3 bg-white/[0.06]" />
                      <Skeleton className="h-3 w-1/5 bg-white/[0.04]" />
                    </div>
                    <Skeleton className="hidden h-3 w-1/4 bg-white/[0.04] sm:block" />
                  </div>
                ))}
              </div>
            ) : error ? (
              <Empty className="min-h-[430px] border-0 text-white">
                <EmptyHeader>
                  <EmptyMedia variant="icon" className="bg-red-400/10 text-red-300">
                    <WifiOff />
                  </EmptyMedia>
                  <EmptyTitle>无法连接本地音乐服务</EmptyTitle>
                  <EmptyDescription className="text-white/45">{error}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                  <Button onClick={() => void loadLibrary()} variant="outline">
                    重新连接
                  </Button>
                </EmptyContent>
              </Empty>
            ) : library && library.songs.length > 0 ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow className="border-white/[0.07] hover:bg-transparent">
                      <TableHead className="w-14 pl-5 text-xs font-normal text-white/35">#</TableHead>
                      <TableHead className="text-xs font-normal text-white/35">歌曲</TableHead>
                      <TableHead className="hidden text-xs font-normal text-white/35 md:table-cell">专辑</TableHead>
                      <TableHead className="w-24 pr-5 text-right text-xs font-normal text-white/35">时长</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {library.songs.map((song, index) => (
                      <TableRow key={song.id} className="group border-white/[0.055] hover:bg-white/[0.035]">
                        <TableCell className="pl-5 text-sm tabular-nums text-white/26">
                          {page * PAGE_SIZE + index + 1}
                        </TableCell>
                        <TableCell className="max-w-0 py-3">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="grid size-10 shrink-0 place-items-center rounded-lg border border-white/[0.06] bg-[linear-gradient(145deg,rgba(41,230,139,0.12),rgba(124,201,255,0.04))] text-[#62eca4]/65">
                              <Music2 className="size-4" />
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-[15px] font-medium text-white/92">{song.title}</p>
                              <p className="mt-0.5 truncate text-sm text-white/38">
                                {song.artists.map((artist) => artist.name).join(" / ") || "未知歌手"}
                              </p>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="hidden max-w-[22rem] truncate text-sm text-white/40 md:table-cell">
                          {song.album ?? "—"}
                        </TableCell>
                        <TableCell className="pr-5 text-right text-sm tabular-nums text-white/34">
                          {formatDuration(song.durationMs)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <div className="flex flex-col gap-3 border-t border-white/[0.07] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                  <p className="text-sm text-white/35">
                    第 {page + 1} / {totalPages} 页 · 共 {library.total.toLocaleString("zh-CN")} 首
                  </p>
                  <Pagination className="mx-0 w-auto justify-start sm:justify-end">
                    <PaginationContent>
                      {pages.map((pageNumber, index) => (
                        <PaginationItem key={pageNumber} className="flex items-center gap-1">
                          {index > 0 && pages[index - 1] !== pageNumber - 1 ? (
                            <span className="px-1 text-white/25">…</span>
                          ) : null}
                          <PaginationLink
                            href="#"
                            isActive={pageNumber === page}
                            onClick={(event) => {
                              event.preventDefault();
                              setPage(pageNumber);
                              window.scrollTo({ top: 0, behavior: "smooth" });
                            }}
                            className="border-white/[0.08] bg-transparent text-white/55 hover:bg-white/[0.07] hover:text-white data-[active=true]:bg-[#29e68b] data-[active=true]:text-[#04110c]"
                          >
                            {pageNumber + 1}
                          </PaginationLink>
                        </PaginationItem>
                      ))}
                    </PaginationContent>
                  </Pagination>
                </div>
              </>
            ) : (
              <Empty className="min-h-[430px] border-0 text-white">
                <EmptyHeader>
                  <EmptyMedia variant="icon" className="bg-white/[0.05] text-white/55">
                    <Search />
                  </EmptyMedia>
                  <EmptyTitle>{query ? "没有找到匹配歌曲" : "曲库还是空的"}</EmptyTitle>
                  <EmptyDescription className="text-white/45">
                    {query ? "换一个歌名、歌手或专辑试试。" : "点击右上角同步 QQ 音乐。"}
                  </EmptyDescription>
                </EmptyHeader>
                {query ? (
                  <EmptyContent>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setSearchDraft("");
                        setQuery("");
                      }}
                    >
                      清除搜索
                    </Button>
                  </EmptyContent>
                ) : null}
              </Empty>
            )}
          </section>
        </div>
      </SidebarInset>
      <Toaster position="bottom-right" richColors />
    </SidebarProvider>
  );
}
