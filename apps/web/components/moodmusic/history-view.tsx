"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { PlaylistHistoryPage } from "@/lib/api-types";

export function HistoryView({
  history,
  error,
  loading,
  retry,
  restorePlaylist,
  busy,
}: {
  history: PlaylistHistoryPage | null;
  error: string | null;
  loading: boolean;
  retry: () => void;
  restorePlaylist: (playlistId: string) => Promise<void>;
  busy: boolean;
}) {
  const labels: Record<string, string> = {
    match: "匹配度",
    emotionCurve: "情绪曲线",
    random: "随机",
    manual: "人工调整",
    similar: "找相似",
    restored: "历史恢复",
  };
  if (error)
    return (
      <div
        role="alert"
        className="rounded-2xl border border-white/10 bg-[#0e1916] p-8 text-center"
      >
        <p className="text-sm text-amber-200">{error}</p>
        <Button className="mt-4" variant="outline" onClick={retry}>
          重新加载历史
        </Button>
      </div>
    );
  if (loading || !history)
    return (
      <div className="space-y-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-24 bg-white/[0.05]" />
        ))}
      </div>
    );
  return (
    <section className="space-y-3">
      <div className="mb-5">
        <h2 className="font-medium">共 {history.total} 个可回放快照</h2>
        <p className="mt-1 text-sm text-white/40">
          每次排序、删除、拖动和追加要求都会保留旧版本。
        </p>
      </div>
      {history.playlists.map((playlist) => (
        <button
          key={playlist.playlistId}
          disabled={busy}
          onClick={() => void restorePlaylist(playlist.playlistId)}
          className="flex w-full flex-col gap-3 rounded-2xl border border-white/[0.08] bg-[#0e1916] p-5 text-left transition hover:border-[#29e68b]/25 hover:bg-[#10201b] sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Badge className="border-white/10 bg-white/[0.04] text-white/55">
                {labels[playlist.sortMode] ?? playlist.sortMode}
              </Badge>
              <span className="text-xs text-white/30">
                {playlist.songCount} 首
              </span>
            </div>
            <p className="mt-2 truncate font-medium text-white/90">
              {playlist.name}
            </p>
            <p className="mt-1 truncate text-sm text-white/35">
              {playlist.description}
            </p>
          </div>
          <div className="shrink-0 text-xs text-white/30">
            {new Date(playlist.createdAt).toLocaleString("zh-CN")}
          </div>
        </button>
      ))}
    </section>
  );
}
