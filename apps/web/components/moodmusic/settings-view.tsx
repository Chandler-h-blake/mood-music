"use client";

import { type FormEvent, useEffect, useState } from "react";
import {
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProfileCard } from "./profile-card";
import { musicApi } from "@/lib/music-api";
import type {
  CredentialStatus,
  JobStatus,
  ModelSettings,
} from "@/lib/api-types";

type Props = {
  settings: ModelSettings | null;
  onSettings: (settings: ModelSettings) => void;
  syncing: boolean;
  syncLibrary: () => Promise<void>;
  job: JobStatus | null;
  jobError: string | null;
  refreshJob: () => Promise<void>;
  progress: number;
  startProfiling: () => Promise<void>;
  goDiscover: () => void;
};

export function SettingsView({
  settings,
  onSettings,
  syncing,
  syncLibrary,
  job,
  jobError,
  refreshJob,
  progress,
  startProfiling,
  goDiscover,
}: Props) {
  const [cookie, setCookie] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [cookieStatus, setCookieStatus] = useState<CredentialStatus | null>(
    null,
  );
  const [cookieError, setCookieError] = useState<string | null>(null);
  const [keyVerified, setKeyVerified] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [libraryCount, setLibraryCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void musicApi
      .cookieStatus()
      .then((status) => {
        if (!cancelled) setCookieStatus(status);
      })
      .catch((error) => {
        if (!cancelled)
          setCookieError(
            error instanceof Error ? error.message : "无法读取连接状态",
          );
      });
    void musicApi
      .library(0, "")
      .then((page) => {
        if (!cancelled) setLibraryCount(page.total);
      })
      .catch(() => {
        /* The library panel provides a retry action. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function action(name: string, operation: () => Promise<void>) {
    setBusy(name);
    try {
      await operation();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "操作失败，请重试");
    } finally {
      setBusy(null);
    }
  }

  async function saveCookie(event: FormEvent) {
    event.preventDefault();
    await action("cookie", async () => {
      try {
        const saved = await musicApi.saveCookie(cookie.trim());
        setCookieStatus(saved);
        setCookieError(null);
        setCookie("");
        try {
          const verified = await musicApi.testCookie();
          setCookieStatus(verified);
          toast.success("QQ 音乐登录状态已验证");
        } catch (error) {
          setCookieStatus({
            ...saved,
            valid: false,
            message: "Cookie 已保存，但登录验证未通过，请重新验证或替换。",
          });
          throw error;
        }
      } finally {
        setCookie("");
      }
    });
  }

  async function saveKey(event: FormEvent) {
    event.preventDefault();
    await action("key", async () => {
      try {
        await musicApi.saveKey(apiKey.trim());
        setApiKey("");
        setKeyVerified(false);
        onSettings(await musicApi.settings());
        await musicApi.testKey();
        setKeyVerified(true);
        toast.success("模型密钥已保存，连接测试通过");
      } finally {
        setApiKey("");
      }
    });
  }

  const disabled = busy !== null || syncing;
  return (
    <section className="mx-auto max-w-3xl space-y-5">
      <div>
        <h2 className="text-xl font-semibold">按顺序完成首次配置</h2>
        <p className="mt-2 text-sm leading-6 text-white/45">
          连接 QQ 音乐 → 配置模型 → 同步喜欢 → 建立画像。Cookie
          和密钥提交后会清空输入框，仅保存在本机加密凭据存储。
        </p>
      </div>
      <Step number={1} title="连接 QQ 音乐" done={cookieStatus?.valid === true}>
        <p className="text-sm leading-6 text-white/45">
          在 QQ 音乐网页版正常登录，打开浏览器开发者工具的“网络”，选择 QQ
          音乐请求，复制请求标头中的 Cookie 值，再粘贴到下面。过期后可在此替换。
        </p>
        <form
          onSubmit={(event) => void saveCookie(event)}
          className="mt-4 space-y-3"
        >
          <label htmlFor="qqmusic-cookie" className="text-sm text-white/65">
            QQ 音乐 Cookie
          </label>
          <Input
            id="qqmusic-cookie"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={cookie}
            onChange={(event) => setCookie(event.target.value)}
            placeholder={
              cookieStatus?.configured
                ? "已配置，粘贴新 Cookie 可替换"
                : "粘贴完整 Cookie 值"
            }
            className="border-white/10 bg-black/20 text-white"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={disabled || !cookie.trim()}
              className="bg-[#29e68b] text-[#04110c]"
            >
              {busy === "cookie" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <KeyRound />
              )}
              保存并验证
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={disabled || !cookieStatus?.configured}
              onClick={() =>
                void action("cookie-test", async () => {
                  try {
                    setCookieStatus(await musicApi.testCookie());
                    setCookieError(null);
                    toast.success("QQ 音乐登录有效");
                  } catch (error) {
                    setCookieStatus((current) =>
                      current
                        ? {
                            ...current,
                            valid: false,
                            message:
                              "验证未通过，请检查网络或替换过期 Cookie。",
                          }
                        : current,
                    );
                    throw error;
                  }
                })
              }
            >
              重新验证
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || !cookieStatus?.configured}
              onClick={() =>
                void action("cookie-clear", async () => {
                  setCookieStatus(await musicApi.clearCookie());
                  setCookie("");
                  setCookieError(null);
                  toast.success("本机 Cookie 已清除");
                })
              }
            >
              <Trash2 />
              清除
            </Button>
          </div>
        </form>
        <p
          role="status"
          className={`mt-3 text-xs ${cookieError || cookieStatus?.valid === false ? "text-amber-200" : "text-white/45"}`}
        >
          {cookieError ?? cookieStatus?.message ?? "正在读取本机连接状态…"}
          {cookieStatus?.maskedAccount
            ? ` · 账号 ${cookieStatus.maskedAccount}`
            : ""}
        </p>
        {cookieError ? (
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={() =>
              void action("cookie-status", async () => {
                setCookieStatus(await musicApi.cookieStatus());
                setCookieError(null);
              })
            }
          >
            重试读取状态
          </Button>
        ) : null}
      </Step>
      <Step number={2} title="配置聊天模型" done={keyVerified}>
        <p className="text-sm text-white/45">
          {settings
            ? `${settings.chatProvider} · ${settings.chatModel}`
            : "正在读取模型设置…"}
        </p>
        <form
          onSubmit={(event) => void saveKey(event)}
          className="mt-4 space-y-3"
        >
          <label htmlFor="api-key" className="text-sm text-white/65">
            DeepSeek API Key
          </label>
          <Input
            id="api-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              settings?.apiKeyConfigured ? "已配置，输入新 Key 可替换" : "sk-…"
            }
            className="border-white/10 bg-black/20 text-white"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={disabled || !apiKey.trim()}
              className="bg-[#29e68b] text-[#04110c]"
            >
              {busy === "key" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <KeyRound />
              )}
              保存并测试
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={disabled || !settings?.apiKeyConfigured}
              onClick={() =>
                void action("key-test", async () => {
                  setKeyVerified(false);
                  await musicApi.testKey();
                  setKeyVerified(true);
                  toast.success("模型连接有效");
                })
              }
            >
              测试已存密钥
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || !settings?.apiKeyConfigured}
              onClick={() =>
                void action("key-clear", async () => {
                  await musicApi.clearKey();
                  setApiKey("");
                  setKeyVerified(false);
                  onSettings(await musicApi.settings());
                  toast.success("本机模型密钥已清除");
                })
              }
            >
              <Trash2 />
              清除
            </Button>
          </div>
        </form>
        <p className="mt-3 text-xs text-white/40">
          {keyVerified
            ? "连接测试通过"
            : settings?.apiKeyConfigured
              ? "密钥已保存，可测试连接。测试会调用模型 API。"
              : "尚未配置模型密钥"}
        </p>
      </Step>
      <Step
        number={3}
        title="同步我的喜欢"
        done={libraryCount !== null && libraryCount > 0}
      >
        <p className="text-sm text-white/45">
          {libraryCount === null
            ? "同步后查看本地曲库数量"
            : `本地共有 ${libraryCount} 首歌曲`}
        </p>
        <Button
          className="mt-4 bg-[#29e68b] text-[#04110c]"
          disabled={disabled || !cookieStatus?.configured}
          onClick={() =>
            void action("sync", async () => {
              await syncLibrary();
              setLibraryCount((await musicApi.library(0, "")).total);
            })
          }
        >
          <RefreshCw className={syncing ? "animate-spin" : ""} />
          {syncing ? "正在同步" : "同步 QQ 音乐"}
        </Button>
      </Step>
      <Step
        number={4}
        title="建立画像并开始选歌"
        done={
          job?.status === "succeeded" && job.failed === 0 && job.completed > 0
        }
      >
        <p className="mb-4 text-sm leading-6 text-white/45">
          先同步歌曲，再建立画像。首次运行会下载
          BGE-M3，请预留磁盘空间。画像通过模型 API
          生成；向量在本机计算。页面刷新后会恢复最新任务进度。
        </p>
        <ProfileCard
          settings={settings}
          job={job}
          error={jobError}
          refreshJob={refreshJob}
          progress={progress}
          startProfiling={startProfiling}
          openSettings={() => document.getElementById("api-key")?.focus()}
        />
        <Button
          variant="outline"
          className="mt-4"
          disabled={
            !settings?.apiKeyConfigured ||
            !libraryCount ||
            job?.status !== "succeeded"
          }
          onClick={goDiscover}
        >
          开始 AI 选歌
        </Button>
      </Step>
    </section>
  );
}

function Step({
  number,
  title,
  done,
  children,
}: {
  number: number;
  title: string;
  done: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0e1916] p-5 sm:p-6">
      <div className="mb-4 flex items-center gap-3">
        <span className="grid size-8 place-items-center rounded-full bg-[#29e68b]/10 text-sm font-medium text-[#75f0af]">
          {done ? <CheckCircle2 className="size-5" /> : number}
        </span>
        <h3 className="font-semibold">{title}</h3>
      </div>
      {children}
    </div>
  );
}
