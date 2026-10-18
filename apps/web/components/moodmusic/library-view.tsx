"use client";

import { useState, useMemo, type FormEvent } from "react";
import { LibraryBig, Database, Clock3, Search, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDuration } from "@/lib/format";
import { PAGE_SIZE } from "@/lib/music-api";
import { ProfileEditor } from "./profile-editor";
import type {
  LibrarySong,
  LibrarySongPage as LibraryPage,
} from "@/lib/api-types";

type LibraryViewProps = {
  library: LibraryPage | null;
  loading: boolean;
  error: string | null;
  page: number;
  totalPages: number;
  query: string;
  searchDraft: string;
  setSearchDraft: (value: string) => void;
  submitSearch: (event: FormEvent<HTMLFormElement>) => void;
  setPage: (page: number) => void;
  reload: () => Promise<void>;
};
export function LibraryView({
  library,
  loading,
  error,
  page,
  totalPages,
  query,
  searchDraft,
  setSearchDraft,
  submitSearch,
  setPage,
  reload,
}: LibraryViewProps) {
  const [editing, setEditing] = useState<LibrarySong | null>(null);
  const pageOptions = useMemo(
    () =>
      [...new Set([0, page - 1, page, page + 1, totalPages - 1])]
        .filter((item) => item >= 0 && item < totalPages)
        .sort((a, b) => a - b),
    [page, totalPages],
  );
  return (
    <>
      <ProfileEditor song={editing} onClose={() => setEditing(null)} />
      <section className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="metric-card">
          <LibraryBig className="size-4 text-[#62eca4]" />
          <div>
            <p className="metric-value">
              {library?.total.toLocaleString("zh-CN") ?? "—"}
            </p>
            <p className="metric-label">{query ? "搜索结果" : "喜欢的歌曲"}</p>
          </div>
        </div>
        <div className="metric-card">
          <Database className="size-4 text-[#7cc9ff]" />
          <div>
            <p className="metric-value">本地音乐库</p>
            <p className="metric-label">歌曲画像与检索已保存在本机</p>
          </div>
        </div>
        <div className="metric-card">
          <Clock3 className="size-4 text-[#d2aeff]" />
          <div>
            <p className="metric-value">增量同步</p>
            <p className="metric-label">只处理发生变化的歌曲</p>
          </div>
        </div>
      </section>
      <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0e1916]">
        <div className="flex flex-col gap-4 border-b border-white/[0.07] p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div>
            <h2 className="font-medium">曲库</h2>
            <p className="mt-1 text-sm text-white/40">
              每页显示 {PAGE_SIZE} 首 · 点击歌名查看和校正画像
            </p>
          </div>
          <form
            onSubmit={submitSearch}
            className="flex w-full gap-2 sm:max-w-md"
          >
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/30" />
              <Input
                value={searchDraft}
                onChange={(event) => setSearchDraft(event.target.value)}
                placeholder="搜索歌曲、歌手或专辑"
                className="h-10 border-white/[0.08] bg-white/[0.04] pl-9 text-white"
              />
            </div>
            <Button
              variant="outline"
              className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white"
            >
              搜索
            </Button>
          </form>
        </div>
        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} className="h-12 bg-white/[0.05]" />
            ))}
          </div>
        ) : error ? (
          <div className="grid min-h-[380px] place-items-center text-center">
            <div>
              <WifiOff className="mx-auto text-red-300" />
              <p className="mt-3 text-white/70">{error}</p>
              <Button
                onClick={() => void reload()}
                variant="outline"
                className="mt-4"
              >
                重新连接
              </Button>
            </div>
          </div>
        ) : library?.songs.length ? (
          <>
            <Table>
              <TableHeader>
                <TableRow className="border-white/[0.07] hover:bg-transparent">
                  <TableHead className="w-14 pl-5 text-white/35">#</TableHead>
                  <TableHead className="text-white/35">歌曲</TableHead>
                  <TableHead className="hidden text-white/35 md:table-cell">
                    专辑
                  </TableHead>
                  <TableHead className="w-24 pr-5 text-right text-white/35">
                    时长
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {library.songs.map((song, index) => (
                  <TableRow
                    key={song.id}
                    className="border-white/[0.055] hover:bg-white/[0.035]"
                  >
                    <TableCell className="pl-5 text-white/25">
                      {page * PAGE_SIZE + index + 1}
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        className="text-left font-medium text-white/90 hover:text-[#75f0af] hover:underline"
                        title="查看或校正歌曲画像"
                        onClick={() => setEditing(song)}
                      >
                        {song.title}
                      </button>
                      <p className="text-sm text-white/38">
                        {song.artists.map((artist) => artist.name).join(" / ")}
                      </p>
                    </TableCell>
                    <TableCell className="hidden max-w-[22rem] truncate text-white/40 md:table-cell">
                      {song.album ?? "—"}
                    </TableCell>
                    <TableCell className="pr-5 text-right text-white/35">
                      {formatDuration(song.durationMs)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex items-center justify-between border-t border-white/[0.07] p-4">
              <p className="text-sm text-white/35">
                第 {page + 1} / {totalPages} 页
              </p>
              <div className="flex gap-1">
                {pageOptions.map((option) => (
                  <Button
                    key={option}
                    size="sm"
                    variant={option === page ? "default" : "ghost"}
                    onClick={() => setPage(option)}
                    className={
                      option === page
                        ? "bg-[#29e68b] text-[#04110c]"
                        : "text-white/50"
                    }
                  >
                    {option + 1}
                  </Button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="grid min-h-[380px] place-items-center text-sm text-white/40">
            {query ? "没有找到匹配歌曲" : "曲库还是空的，请先同步 QQ 音乐"}
          </div>
        )}
      </section>
    </>
  );
}
