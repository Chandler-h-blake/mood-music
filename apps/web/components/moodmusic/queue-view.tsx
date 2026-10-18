"use client";

import { useState } from "react";
import {
  ListMusic,
  Play,
  GitCompareArrows,
  Waves,
  Shuffle,
  LoaderCircle,
  Sparkles,
  GripVertical,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import type { QueueSong, TemporaryQueue } from "@/lib/api-types";

type QueueViewProps = {
  queue: TemporaryQueue | null;
  busy: boolean;
  goDiscover: () => void;
  sortQueue: (mode: "match" | "emotionCurve" | "random") => Promise<void>;
  removeCandidate: (candidateId: string) => Promise<void>;
  findSimilar: (candidateId: string) => Promise<void>;
  saveOrder: (candidateIds: string[]) => Promise<void>;
  refineQueue: (requirement: string) => Promise<boolean>;
  playQueue: () => Promise<void>;
};

export function QueueView({
  queue,
  busy,
  goDiscover,
  sortQueue,
  removeCandidate,
  findSimilar,
  saveOrder,
  refineQueue,
  playQueue,
}: QueueViewProps) {
  const [explaining, setExplaining] = useState<QueueSong | null>(null);
  const [refinement, setRefinement] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(100);
  if (!queue)
    return (
      <div className="grid min-h-[460px] place-items-center rounded-2xl border border-dashed border-white/10">
        <div className="text-center">
          <ListMusic className="mx-auto size-10 text-white/25" />
          <h2 className="mt-4 font-medium">还没有临时队列</h2>
          <p className="mt-1 text-sm text-white/40">先描述一种想听的感觉。</p>
          <Button
            onClick={goDiscover}
            className="mt-5 bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"
          >
            去 AI 选歌
          </Button>
        </div>
      </div>
    );
  const sortLabel =
    {
      match: "匹配度排序",
      emotionCurve: "情绪曲线",
      random: "随机排序",
      manual: "人工顺序",
      similar: "相似歌曲顺序",
      restored: "历史恢复",
    }[queue.sortMode] ?? queue.sortMode;
  const vocalLabels: Record<string, string> = {
    male_solo: "男声独唱",
    female_solo: "女声独唱",
    mixed_duet: "男女对唱",
    male_duet: "双男声",
    female_duet: "双女声",
    group: "组合",
    choir: "合唱团",
    instrumental: "纯音乐",
    other: "其他人声",
  };
  const languageLabels: Record<string, string> = {
    zh: "中文/普通话",
    yue: "粤语",
    en: "英语",
    ja: "日语",
    ko: "韩语",
    es: "西班牙语",
    fr: "法语",
    de: "德语",
    ru: "俄语",
    other: "其他语言",
  };
  const enforcedConstraints = [
    ...(queue.intent.requiredVocalModes?.length
      ? [
          `只保留：${queue.intent.requiredVocalModes.map((value) => vocalLabels[value] ?? value).join("、")}`,
        ]
      : []),
    ...(queue.intent.excludedVocalModes?.length
      ? [
          `排除：${queue.intent.excludedVocalModes.map((value) => vocalLabels[value] ?? value).join("、")}`,
        ]
      : []),
    ...(queue.intent.allowedLanguages?.length
      ? [
          `语言：${queue.intent.allowedLanguages.map((value) => languageLabels[value] ?? value).join("、")}`,
        ]
      : []),
    ...(queue.intent.excludedLanguages?.length
      ? [
          `排除语言：${queue.intent.excludedLanguages.map((value) => languageLabels[value] ?? value).join("、")}`,
        ]
      : []),
    ...(queue.intent.instrumentalAllowed === false ? ["排除纯音乐"] : []),
    ...(queue.intent.maxEnergy != null
      ? [`最高能量：${Math.round(queue.intent.maxEnergy * 100)}%`]
      : []),
  ];
  const dropOn = (targetId: string) => {
    if (!dragging || dragging === targetId || busy) return;
    const ids = queue.songs.map((song) => song.candidateId);
    const from = ids.indexOf(dragging);
    const to = ids.indexOf(targetId);
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    setDragging(null);
    void saveOrder(ids);
  };
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0e1916]">
      <div className="border-b border-white/[0.07] p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <Badge className="border-[#29e68b]/20 bg-[#29e68b]/10 text-[#75f0af]">
              临时队列 · {sortLabel}
            </Badge>
            <h2 className="mt-3 text-xl font-semibold">{queue.name}</h2>
            <p className="mt-2 text-sm text-white/42">
              已评估 {queue.evaluatedCount} 首 · 当前 {queue.matchedCount} 首 ·
              阈值 {(queue.intent.threshold * 100).toFixed(0)} 分
            </p>
            {queue.randomSeed !== null ? (
              <p className="mt-1 text-xs text-white/30">
                随机种子：{queue.randomSeed}
              </p>
            ) : null}
            {queue.intent.exclusions.length ? (
              <p className="mt-2 text-xs text-white/35">
                排除要求：{queue.intent.exclusions.join("、")}
              </p>
            ) : null}
            {enforcedConstraints.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {enforcedConstraints.map((constraint) => (
                  <Badge
                    key={constraint}
                    variant="outline"
                    className="border-[#29e68b]/20 bg-[#29e68b]/5 text-[#75f0af]"
                  >
                    已执行 · {constraint}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
          <Button
            disabled={busy || queue.songs.length === 0}
            onClick={() => void playQueue()}
            title="由 MoodMusic 托管歌单顺序并通过本机 QQ 音乐输出"
            className="bg-[#29e68b] text-[#04110c]"
          >
            <Play />
            {busy ? "正在连接 QQ 音乐" : "交给 MoodMusic 播放"}
          </Button>
        </div>
        <p className="mt-3 text-xs leading-5 text-white/40">
          {queue.diagnostics?.scoreNote ?? "匹配分是排序依据，不代表准确率。"}{" "}
          当前采用语义 72% + 特征 28%；缺少特征时回退到语义分。
        </p>
        {queue.diagnostics?.missingProfileCount ? (
          <p className="mt-2 text-xs text-amber-200/80">
            曲库中另有 {queue.diagnostics.missingProfileCount}{" "}
            首缺少当前模型可用画像，尚未参与本次匹配；可先更新画像。
          </p>
        ) : null}
        <div className="mt-5 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void sortQueue("match")}
            className="border-white/10 bg-white/[0.04] text-white"
          >
            <GitCompareArrows />
            匹配度
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void sortQueue("emotionCurve")}
            className="border-white/10 bg-white/[0.04] text-white"
          >
            <Waves />
            情绪曲线
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void sortQueue("random")}
            className="border-white/10 bg-white/[0.04] text-white"
          >
            <Shuffle />
            随机
          </Button>
          {busy ? (
            <span className="flex items-center gap-2 px-2 text-xs text-white/40">
              <LoaderCircle className="size-4 animate-spin" />
              正在保存新快照
            </span>
          ) : null}
        </div>
        <form
          className="mt-4 flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            const value = refinement.trim();
            if (value.length < 2) return;
            void refineQueue(value).then((saved) => {
              if (saved)
                setRefinement((current) =>
                  current.trim() === value ? "" : current,
                );
            });
          }}
        >
          <Input
            value={refinement}
            onChange={(event) => setRefinement(event.target.value)}
            placeholder="继续要求，例如：再少一点人声，前半段更轻快"
            className="border-white/10 bg-black/20 text-white"
          />
          <Button
            disabled={busy || refinement.trim().length < 2}
            className="bg-[#29e68b] text-[#04110c] hover:bg-[#50efa1]"
          >
            <Sparkles />
            追加要求
          </Button>
        </form>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="border-white/[0.07] hover:bg-transparent">
            <TableHead className="w-14 pl-4 text-white/35">#</TableHead>
            <TableHead className="text-white/35">歌曲</TableHead>
            <TableHead className="hidden text-white/35 md:table-cell">
              匹配构成
            </TableHead>
            <TableHead className="w-20 text-right text-white/35">
              匹配度
            </TableHead>
            <TableHead className="w-28 pr-4 text-right text-white/35">
              操作
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {queue.songs.slice(0, visibleCount).map((song, index) => (
            <TableRow
              key={song.candidateId}
              draggable={!busy}
              onDragStart={() => setDragging(song.candidateId)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => dropOn(song.candidateId)}
              className={`border-white/[0.055] hover:bg-white/[0.035] ${dragging === song.candidateId ? "opacity-40" : ""}`}
            >
              <TableCell className="pl-4 text-white/25">
                <span className="flex items-center gap-1">
                  <GripVertical className="size-3 cursor-grab" />
                  {index + 1}
                </span>
              </TableCell>
              <TableCell>
                <p className="font-medium text-white/90">{song.title}</p>
                <p className="text-sm text-white/38">
                  {song.artists.map((artist) => artist.name).join(" / ")}
                </p>
                {song.explanation ? (
                  <button
                    type="button"
                    className="mt-2 block text-xs text-[#75f0af]/80 hover:underline"
                    onClick={() => setExplaining(song)}
                  >
                    为什么选中 · 画像 v{song.explanation.profileVersion}
                  </button>
                ) : (
                  <p className="mt-1 text-xs text-white/30">
                    此历史快照未保存画像依据
                  </p>
                )}
              </TableCell>
              <TableCell className="hidden text-xs text-white/38 md:table-cell">
                语义 {(song.semanticScore * 100).toFixed(0)} 分 · 特征{" "}
                {(song.featureScore * 100).toFixed(0)} 分
              </TableCell>
              <TableCell className="text-right font-medium text-[#75f0af]">
                {(song.score * 100).toFixed(0)} 分
              </TableCell>
              <TableCell className="pr-4">
                <div className="flex justify-end gap-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    disabled={busy}
                    title="以这首歌为基准找相似"
                    onClick={() => void findSimilar(song.candidateId)}
                    className="size-8 text-white/45 hover:text-[#75f0af]"
                  >
                    <GitCompareArrows />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    disabled={busy}
                    title="从当前会话移除"
                    onClick={() => void removeCandidate(song.candidateId)}
                    className="size-8 text-white/45 hover:text-red-300"
                  >
                    <Trash2 />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {visibleCount < queue.songs.length ? (
        <div className="border-t border-white/[0.07] p-4 text-center">
          <Button
            variant="ghost"
            onClick={() => setVisibleCount((value) => value + 100)}
            className="text-white/55"
          >
            再显示 100 首
          </Button>
        </div>
      ) : null}
      {queue.songs.length === 0 ? (
        <div className="p-12 text-center text-sm text-white/40">
          <p>当前队列为空，可以调整要求或重新搜索。</p>
          {queue.diagnostics ? (
            <div className="mx-auto mt-4 max-w-xl space-y-2 text-left">
              <p>
                本次搜索覆盖曲库 {queue.diagnostics.libraryCount} 首中的{" "}
                {queue.diagnostics.profiledCount} 首可用画像。
              </p>
              {queue.diagnostics.rejections.map((item) => (
                <p key={item.reason}>
                  {item.reason}：{item.count} 首
                </p>
              ))}
              <p className="text-white/30">
                以上为搜索时的筛选统计；人工移除的歌曲不会计入。系统保留明确要求，不自动放宽筛选。
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
      <Dialog
        open={explaining !== null}
        onOpenChange={(open) => {
          if (!open) setExplaining(null);
        }}
      >
        <DialogContent className="max-h-[85vh] w-[calc(100vw_-_2rem)] overflow-y-auto border-white/10 bg-[#0e1916] text-white sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{explaining?.title} · 选歌依据</DialogTitle>
            <DialogDescription className="text-white/45">
              搜索时保存的画像依据，后续人工修正不会改写此历史解释。
            </DialogDescription>
          </DialogHeader>
          {explaining?.explanation ? (
            <div className="space-y-4 text-sm leading-7 text-white/65">
              <p>{explaining.explanation.basis}</p>
              <p>{explaining.explanation.summary}</p>
              <ul className="list-inside list-disc space-y-2">
                {explaining.explanation.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              {explaining.explanation.uncertainties.length ? (
                <p className="text-amber-200/80">
                  不确定项：{explaining.explanation.uncertainties.join("；")}
                </p>
              ) : null}
              <p className="text-xs text-white/45">
                画像自评可信度{" "}
                {(explaining.explanation.confidence * 100).toFixed(0)}{" "}
                分，非实测准确率。
              </p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
