"use client";

import {
  Music2,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  LoaderCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { formatDuration } from "@/lib/format";
import type {
  TemporaryQueue,
  PCPlaybackState as PlaybackState,
  PCPlaybackActionInput,
} from "@/lib/api-types";
type PlaybackAction = PCPlaybackActionInput["action"];

export function PlayerView({
  queue,
  playback,
  active,
  busy,
  control,
  openQueue,
}: {
  queue: TemporaryQueue | null;
  playback: PlaybackState | null;
  active: boolean;
  busy: boolean;
  control: (action: PlaybackAction) => Promise<void>;
  openQueue: () => void;
}) {
  if (!queue || !active)
    return (
      <div className="grid min-h-[520px] place-items-center rounded-3xl border border-dashed border-white/10 bg-[#0e1916]">
        <div className="max-w-md px-6 text-center">
          <Play className="mx-auto size-12 text-[#75f0af]/60" />
          <h2 className="mt-5 text-xl font-semibold">播放器还没有接管歌单</h2>
          <p className="mt-2 text-sm leading-6 text-white/40">
            先在临时队列中点击“交给 MoodMusic 播放”。声音仍由已登录的 QQ
            音乐客户端输出。
          </p>
          <Button
            onClick={openQueue}
            className="mt-6 bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"
          >
            打开临时队列
          </Button>
        </div>
      </div>
    );
  const normalize = (value: string | null) =>
    (value ?? "").toLocaleLowerCase().replace(/\s/g, "");
  const titleMatches = queue.songs
    .map((song, index) => ({ song, index }))
    .filter(
      ({ song }) =>
        normalize(song.title) === normalize(playback?.title ?? null),
    );
  const artistMatches = titleMatches.filter(
    ({ song }) =>
      playback?.artist &&
      song.artists.some((artist) =>
        normalize(playback.artist).includes(normalize(artist.name)),
      ),
  );
  const currentIndex =
    titleMatches.length === 1
      ? titleMatches[0].index
      : artistMatches.length === 1
        ? artistMatches[0].index
        : -1;
  const current = queue.songs[currentIndex];
  const duration = playback?.durationMs ?? current?.durationMs ?? null;
  const position = playback?.positionMs ?? 0;
  const progress = duration
    ? Math.min(100, Math.max(0, (position / duration) * 100))
    : 0;
  const isPlaying = playback?.status === "playing";
  const unavailable =
    !playback || ["unavailable", "closed"].includes(playback.status);
  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
      <div className="flex min-h-[560px] flex-col justify-between overflow-hidden rounded-3xl border border-[#29e68b]/15 bg-[radial-gradient(circle_at_50%_10%,rgba(41,230,139,0.16),transparent_44%),#0e1916] p-6 sm:p-10">
        <div className="flex items-center justify-between">
          <Badge className="border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]">
            {unavailable ? "播放状态未确认" : "MoodMusic 托管中"}
          </Badge>
          <span className="text-xs text-white/35">
            {currentIndex >= 0
              ? `第 ${currentIndex + 1} / ${queue.songs.length} 首`
              : "尚未确认队列位置"}
          </span>
        </div>
        <div className="py-10 text-center">
          <div className="mx-auto grid size-40 place-items-center rounded-[2.5rem] border border-white/10 bg-black/20 text-[#75f0af] shadow-[0_25px_80px_rgba(0,0,0,0.35)] sm:size-52">
            <Music2 className="size-20 opacity-70" />
          </div>
          <h2 className="mt-8 text-2xl font-semibold sm:text-4xl">
            {playback?.title ?? current?.title ?? "正在连接 QQ 音乐"}
          </h2>
          <p className="mt-3 text-base text-white/42">
            {playback?.artist ??
              current?.artists.map((artist) => artist.name).join(" / ") ??
              "—"}
          </p>
        </div>
        <div>
          <Progress value={progress} className="h-1.5 bg-white/[0.08]" />
          <div className="mt-2 flex justify-between text-xs text-white/30">
            <span>{formatDuration(position)}</span>
            <span>{formatDuration(duration)}</span>
          </div>
          <div className="mt-6 flex items-center justify-center gap-4">
            <Button
              size="icon"
              variant="ghost"
              disabled={
                busy ||
                unavailable ||
                queue.songs.length < 2 ||
                currentIndex === 0
              }
              onClick={() => void control("previous")}
              title="上一首"
              className="size-12 rounded-full text-white/65 hover:bg-white/10 hover:text-white"
            >
              <SkipBack className="size-6" />
            </Button>
            <Button
              size="icon"
              disabled={busy || unavailable}
              onClick={() => void control(isPlaying ? "pause" : "play")}
              title={isPlaying ? "暂停" : "继续"}
              className="size-16 rounded-full bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"
            >
              {busy ? (
                <LoaderCircle className="size-7 animate-spin" />
              ) : isPlaying ? (
                <Pause className="size-7 fill-current" />
              ) : (
                <Play className="size-7 fill-current" />
              )}
            </Button>
            <Button
              size="icon"
              variant="ghost"
              disabled={
                busy ||
                unavailable ||
                queue.songs.length < 2 ||
                currentIndex >= queue.songs.length - 1
              }
              onClick={() => void control("next")}
              title="下一首"
              className="size-12 rounded-full text-white/65 hover:bg-white/10 hover:text-white"
            >
              <SkipForward className="size-6" />
            </Button>
          </div>
          <p
            role="status"
            className={`mt-4 text-center text-xs leading-5 ${unavailable ? "text-amber-200" : "text-white/40"}`}
          >
            {playback?.message ?? "正在获取播放状态"}
          </p>
          <p className="mt-6 text-center text-xs leading-5 text-white/30">
            请在这里切歌，MoodMusic 会直接点播目标歌曲，不经过 QQ 音乐原有队列。
          </p>
        </div>
      </div>
      <div className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0e1916]">
        <div className="border-b border-white/[0.07] p-5">
          <h3 className="font-semibold">接下来播放</h3>
          <p className="mt-1 text-xs text-white/35">{queue.name}</p>
        </div>
        <div className="max-h-[650px] overflow-y-auto">
          {queue.songs.map((song, index) => (
            <div
              key={song.candidateId}
              className={`flex items-center gap-3 border-b border-white/[0.05] px-5 py-3 ${index === currentIndex ? "bg-[#29e68b]/10" : ""}`}
            >
              <span
                className={`w-6 text-xs ${index === currentIndex ? "text-[#75f0af]" : "text-white/25"}`}
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p
                  className={`truncate text-sm ${index === currentIndex ? "font-medium text-[#75f0af]" : "text-white/75"}`}
                >
                  {song.title}
                </p>
                <p className="truncate text-xs text-white/32">
                  {song.artists.map((artist) => artist.name).join(" / ")}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
