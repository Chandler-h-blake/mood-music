"use client";

import { type FormEvent, useEffect, useId, useState } from "react";
import { LoaderCircle, LockKeyhole } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { musicApi } from "@/lib/music-api";
import type {
  LibrarySong,
  SongProfileData,
  SongProfileView,
} from "@/lib/api-types";

type Props = { song: LibrarySong | null; onClose: () => void };
const fields = [
  ["energy", "能量"],
  ["valence", "情绪明亮度"],
  ["danceability", "律动"],
  ["acousticness", "原声程度"],
] as const;
const emotions = [
  ["joy", "快乐"],
  ["sadness", "悲伤"],
  ["loneliness", "孤独"],
  ["warmth", "温暖"],
  ["hope", "希望"],
  ["tension", "紧张"],
  ["calm", "平静"],
] as const;

export function ProfileEditor({ song, onClose }: Props) {
  return (
    <Dialog
      open={song !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] w-[calc(100vw_-_2rem)] overflow-y-auto border-white/10 bg-[#0e1916] text-white sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{song?.title} · 歌曲画像</DialogTitle>
          <DialogDescription className="text-white/45">
            查看依据并纠正误判。未知数值留空，0～1 表示相对强度。
          </DialogDescription>
        </DialogHeader>
        {song ? <ProfileForm key={song.id} song={song} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function ProfileForm({ song }: { song: LibrarySong }) {
  const id = useId();
  const [saved, setSaved] = useState<SongProfileView | null>(null);
  const [draft, setDraft] = useState<SongProfileData | null>(null);
  const [locked, setLocked] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void musicApi
      .profile(song.id, controller.signal)
      .then((profile) => {
        if (controller.signal.aborted) return;
        setSaved(profile);
        setDraft(profile?.profile ?? null);
        setLocked(profile?.model === "user" ? profile.locked : true);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : "无法读取画像");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [song.id, revision]);

  const change = <K extends keyof SongProfileData>(
    key: K,
    value: SongProfileData[K],
  ) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || !saved) return;
    setSaving(true);
    setError(null);
    try {
      const result = await musicApi.saveProfile(song.id, {
        profile: draft,
        expectedVersion: saved.profileVersion,
        locked,
      });
      setSaved(result);
      setDraft(result.profile);
      setLocked(result.locked);
      toast.success("人工画像和检索向量已保存，新选歌会使用此版本");
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "保存失败，原画像已保留",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <p className="flex items-center gap-2 text-sm text-white/50">
        <LoaderCircle className="size-4 animate-spin" />
        正在读取画像…
      </p>
    );
  if (!draft || !saved)
    return (
      <div className="text-sm text-white/50">
        {error ?? "这首歌还没有画像，请先运行画像任务。"}
        {error ? (
          <Button
            variant="ghost"
            onClick={() => {
              setError(null);
              setLoading(true);
              setRevision((value) => value + 1);
            }}
          >
            重新读取
          </Button>
        ) : null}
      </div>
    );
  const list = (value: string) =>
    value
      .split(/[,，、\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  return (
    <form onSubmit={(event) => void save(event)} className="space-y-5">
      <div className="rounded-xl border border-white/10 bg-black/15 p-3 text-xs leading-6 text-white/50">
        <p>{saved.basis}</p>
        <p>
          版本 {saved.profileVersion} · {saved.model} ·{" "}
          {new Date(saved.createdAt).toLocaleString("zh-CN")}
        </p>
        <p>
          可信度为模型自评或人工判断，不代表实测准确率。修改后生成新版本；历史队列保留当时的解释。
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="演唱语言" id={`${id}-language`}>
          <Input
            id={`${id}-language`}
            value={draft.language ?? ""}
            onChange={(event) => change("language", event.target.value || null)}
            placeholder="未知留空，例如：普通话、粤语"
          />
        </Field>
        <Field label="人声类型" id={`${id}-vocal`}>
          <Input
            id={`${id}-vocal`}
            value={draft.vocalType ?? ""}
            onChange={(event) =>
              change("vocalType", event.target.value || null)
            }
            placeholder="未知留空，例如：女声独唱、纯音乐"
          />
        </Field>
      </div>
      <Field label="流派（逗号分隔）" id={`${id}-genres`}>
        <ListInput
          id={`${id}-genres`}
          values={draft.genres}
          onChange={(value) => change("genres", list(value))}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        {fields.map(([key, label]) => (
          <NumberField
            key={key}
            id={`${id}-${key}`}
            label={label}
            value={draft[key]}
            onChange={(value) => change(key, value)}
          />
        ))}
      </div>
      <Field label="整体感觉描述" id={`${id}-description`}>
        <Textarea
          id={`${id}-description`}
          required
          maxLength={1200}
          rows={4}
          value={draft.semanticDescription}
          onChange={(event) =>
            change("semanticDescription", event.target.value)
          }
        />
        <p className="mt-1 text-xs text-white/35">
          请同时纠正描述中的误判，检索会结合描述与画像字段生成向量。
        </p>
      </Field>
      <details className="rounded-xl border border-white/10 p-3">
        <summary className="cursor-pointer text-sm text-white/65">
          更多画像字段与情绪强度
        </summary>
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {emotions.map(([key, label]) => (
              <NumberField
                key={key}
                id={`${id}-${key}`}
                label={label}
                value={draft.emotions[key]}
                onChange={(value) =>
                  change("emotions", { ...draft.emotions, [key]: value })
                }
              />
            ))}
          </div>
          {(
            [
              ["scenes", "适用场景"],
              ["themes", "主题"],
              ["arrangement", "编曲特征"],
            ] as const
          ).map(([key, label]) => (
            <Field key={key} label={`${label}（逗号分隔）`} id={`${id}-${key}`}>
              <ListInput
                id={`${id}-${key}`}
                values={draft[key]}
                onChange={(value) => change(key, list(value))}
              />
            </Field>
          ))}
          <Field label="身份与版本说明" id={`${id}-identity`}>
            <Input
              id={`${id}-identity`}
              value={draft.identitySummary}
              onChange={(event) =>
                change("identitySummary", event.target.value)
              }
            />
          </Field>
          <NumberField
            id={`${id}-confidence`}
            label="画像可信度（自评）"
            value={draft.confidence}
            onChange={(value) => {
              if (value !== null) change("confidence", value);
            }}
            required
          />
        </div>
      </details>
      <label className="flex items-start gap-2 text-sm leading-6 text-white/65">
        <input
          type="checkbox"
          checked={locked}
          onChange={(event) => setLocked(event.target.checked)}
          className="mt-1 accent-[#29e68b]"
        />
        <span>
          <LockKeyhole className="mr-1 inline size-4" />
          锁定这份画像，自动更新和全量重建都保留人工修正。取消锁定后，后续重建可以替换。
        </span>
      </label>
      {error ? (
        <div role="alert" className="text-sm text-amber-200">
          {error}
          <Button
            type="button"
            variant="ghost"
            disabled={saving}
            onClick={() => {
              setError(null);
              setLoading(true);
              setRevision((value) => value + 1);
            }}
          >
            重新读取最新版本
          </Button>
        </div>
      ) : null}
      <Button
        disabled={saving || !draft.semanticDescription.trim()}
        className="bg-[#29e68b] text-[#04110c]"
      >
        {saving ? <LoaderCircle className="animate-spin" /> : null}
        {saving ? "正在生成向量并保存" : "保存人工画像"}
      </Button>
    </form>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 [&_input]:border-white/10 [&_input]:bg-black/20 [&_textarea]:border-white/10 [&_textarea]:bg-black/20">
      <label htmlFor={id} className="text-xs text-white/55">
        {label}
      </label>
      {children}
    </div>
  );
}
function NumberField({
  id,
  label,
  value,
  onChange,
  required = false,
}: {
  id: string;
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  required?: boolean;
}) {
  return (
    <Field label={label} id={id}>
      <Input
        id={id}
        type="number"
        min={0}
        max={1}
        step={0.01}
        required={required}
        value={value ?? ""}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? null : Number(event.target.value),
          )
        }
        placeholder="未知"
      />
    </Field>
  );
}
function ListInput({
  id,
  values,
  onChange,
}: {
  id: string;
  values: string[];
  onChange: (value: string) => void;
}) {
  const [text, setText] = useState(values.join("、"));
  return (
    <Input
      id={id}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        onChange(event.target.value);
      }}
    />
  );
}
