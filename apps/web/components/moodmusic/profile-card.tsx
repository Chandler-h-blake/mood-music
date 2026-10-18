"use client";

import { Database, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { ModelSettings, JobStatus as Job } from "@/lib/api-types";

export function ProfileCard({
  settings,
  job,
  error,
  refreshJob,
  progress,
  startProfiling,
  openSettings,
}: {
  settings: ModelSettings | null;
  job: Job | null;
  error: string | null;
  refreshJob: () => Promise<void>;
  progress: number;
  startProfiling: () => void;
  openSettings: () => void;
}) {
  const running = !!job && ["queued", "running"].includes(job.status);
  const label =
    job?.status === "queued"
      ? "等待执行器"
      : job?.status === "running"
        ? "画像进行中"
        : job?.status === "failed"
          ? "继续未完成画像"
          : job?.status === "succeeded" && job.failed
            ? `重试 ${job.failed} 首`
            : "更新全部画像";
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0e1916] p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-medium">歌曲多角度画像</h3>
          <p className="mt-1 text-sm text-white/40">
            处理新增、变化或失败的歌曲，保留人工锁定画像
          </p>
        </div>
        {settings?.apiKeyConfigured ? (
          <Button
            variant="outline"
            disabled={running}
            onClick={() => void startProfiling()}
            className="border-white/10 bg-white/[0.04] text-white"
          >
            {running ? <LoaderCircle className="animate-spin" /> : <Database />}
            {label}
          </Button>
        ) : (
          <Button variant="outline" onClick={openSettings}>
            先设置 API Key
          </Button>
        )}
      </div>
      {job ? (
        <div className="mt-5">
          <div className="mb-2 flex justify-between text-xs text-white/45">
            <span>
              {job.status === "succeeded"
                ? job.failed
                  ? `主体完成，跳过 ${job.failed} 首`
                  : "已完成"
                : job.status === "failed"
                  ? "任务中断，可继续"
                  : label}
            </span>
            <span>
              {job.completed + job.failed} / {job.total}
            </span>
          </div>
          <Progress
            value={Math.min(100, progress)}
            className="h-1.5 bg-white/[0.06]"
          />
          {job.lastError ? (
            <p className="mt-2 text-xs text-amber-200">{job.lastError}</p>
          ) : null}
          {running ? (
            <p className="mt-2 text-xs leading-5 text-white/40">
              进度已保存，刷新页面会自动恢复。服务重启后最多等待 90
              秒续跑；长时间排队请通过启动脚本启动画像 worker。
            </p>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <div className="mt-3 text-xs text-amber-200" role="alert">
          {error}
          <Button size="sm" variant="ghost" onClick={() => void refreshJob()}>
            重新读取任务
          </Button>
        </div>
      ) : null}
    </div>
  );
}
