import { test, expect, type Page } from "@playwright/test";
import fixture from "./fixtures/workspace.json" with { type: "json" };
import { ManualProfileUpdateSchema } from "../lib/api-schemas";
import type { SongProfileView } from "../lib/api-types";

// Every API request is intercepted. These tests never use system credentials,
// launch QQ Music, or call a real model provider.
async function mockWorkspace(
  page: Page,
  options: { playbackError?: boolean; sameTitle?: boolean } = {},
) {
  const first = { ...fixture.queue.songs[0], title: "A第一首" };
  const second = {
    ...first,
    candidateId: "00000000-0000-0000-0000-000000000002",
    songId: "00000000-0000-0000-0000-000000000003",
    sourceTrackId: "fictional-browser-1",
    title: options.sameTitle ? first.title : "A第二首",
    artists: [{ name: "第二位歌手" }],
  };
  const queueA = {
    ...fixture.queue,
    name: "正在播放队列A",
    matchedCount: 2,
    songs: [first, second],
  };
  const queueB = {
    ...fixture.queue,
    playlistId: "00000000-0000-0000-0000-000000000004",
    name: "编辑中的队列B",
    songs: [{ ...first, title: "B第一首" }],
  };
  let generated = 0,
    historyCalls = 0;
  let profile: SongProfileView = fixture.profile;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const headers = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "*",
      "Access-Control-Allow-Headers": "*",
    };
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    let result: unknown,
      status = 200;
    if (path === "/api/v1/settings")
      result = { ...fixture.settings, apiKeyConfigured: true };
    else if (path === "/api/v1/library/songs") {
      const query = url.searchParams.get("q");
      if (query === "慢查询")
        await new Promise((resolve) => setTimeout(resolve, 600));
      result = {
        page: 0,
        pageSize: 50,
        total: 1,
        songs: [{ ...fixture.song, title: query || fixture.song.title }],
      };
    } else if (path === "/api/v1/profile-jobs/latest") result = null;
    else if (path === "/api/v1/search-sessions")
      result = ++generated === 1 ? queueA : queueB;
    else if (path.endsWith("/refinements")) {
      result = {
        detail: { code: "test.failure", message: "模拟追加要求失败" },
      };
      status = 503;
    } else if (path === "/api/v1/playback/queues")
      result = {
        status: "completed",
        playlistId: queueA.playlistId,
        acceptedCount: 2,
        currentIndex: 0,
        sourceTrackId: first.sourceTrackId,
        title: first.title,
        artist: first.artists[0].name,
        observed: true,
        message: "开始播放",
      };
    else if (path === "/api/v1/playback/state") {
      if (options.playbackError) {
        result = {
          detail: { code: "test.failure", message: "播放器状态读取失败" },
        };
        status = 503;
      } else
        result = {
          status: "playing",
          title: first.title,
          artist: options.sameTitle
            ? second.artists[0].name
            : first.artists[0].name,
          album: null,
          positionMs: 1000,
          durationMs: 180000,
          canPlay: true,
          canPause: true,
          canNext: true,
          canPrevious: false,
          message: "播放中",
        };
    } else if (path === "/api/v1/generated-playlists") {
      if (++historyCalls === 1) {
        result = {
          detail: { code: "test.failure", message: "模拟历史加载失败" },
        };
        status = 503;
      } else result = { page: 0, pageSize: 50, total: 0, playlists: [] };
    } else if (path.endsWith("/profile")) {
      if (method === "PUT") {
        const update = ManualProfileUpdateSchema.parse(request.postDataJSON());
        expect(update.expectedVersion).toBe(profile.profileVersion);
        expect(update.locked).toBe(true);
        profile = {
          ...profile,
          profileVersion: profile.profileVersion + 1,
          profile: update.profile,
          locked: update.locked,
          model: "user",
          basis: "用户人工校正",
        };
      }
      result = profile;
    } else {
      await route.abort("blockedbyclient");
      throw new Error(`未模拟的请求：${method} ${path}`);
    }
    await route.fulfill({ status, json: result, headers }).catch((error) => {
      // A cancelled slow search intentionally closes its intercepted request.
      if (url.searchParams.get("q") !== "慢查询") throw error;
    });
  });
  await page.goto("/", { waitUntil: "networkidle" });
  return { errors, profile: () => profile };
}

async function generate(page: Page) {
  await page.getByRole("button", { name: "AI 选歌", exact: true }).click();
  await page.getByRole("button", { name: "生成临时队列", exact: true }).click();
  await expect(page.getByText("临时队列 · 匹配度排序")).toBeVisible();
}

test("编辑新队列保留正在播放的队列快照", async ({ page }) => {
  const state = await mockWorkspace(page);
  await generate(page);
  await page
    .getByRole("button", { name: "交给 MoodMusic 播放", exact: true })
    .click();
  await expect(page.getByText("A第二首", { exact: true })).toBeVisible();
  await generate(page);
  await page.getByRole("button", { name: "播放器", exact: true }).click();
  await expect(page.getByText("A第二首", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "下一首", exact: true }),
  ).toBeEnabled();
  expect(state.errors).toEqual([]);
});

test("追加要求失败保留输入", async ({ page }) => {
  await mockWorkspace(page);
  await generate(page);
  const input = page.getByPlaceholder(
    "继续要求，例如：再少一点人声，前半段更轻快",
  );
  await input.fill("少一点人声");
  await page.getByRole("button", { name: "追加要求", exact: true }).click();
  await expect(
    page.getByText("模拟追加要求失败", { exact: true }),
  ).toBeVisible();
  await expect(input).toHaveValue("少一点人声");
});

test("历史失败退出加载状态并可重试", async ({ page }) => {
  await mockWorkspace(page);
  await page.getByRole("button", { name: "队列历史", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "模拟历史加载失败" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "重新加载历史", exact: true }).click();
  await expect(page.getByText("共 0 个可回放快照")).toBeVisible();
});

test("播放状态读取失败明确提示并停止显示旧状态", async ({ page }) => {
  await mockWorkspace(page, { playbackError: true });
  await generate(page);
  await page
    .getByRole("button", { name: "交给 MoodMusic 播放", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "播放器状态读取失败" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "继续", exact: true }),
  ).toBeDisabled();
});

test("慢搜索结果不会覆盖新搜索", async ({ page }) => {
  await mockWorkspace(page);
  const input = page.getByPlaceholder("搜索歌曲、歌手或专辑");
  await input.fill("慢查询");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await input.fill("快速查询");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "快速查询", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(800);
  await expect(
    page.getByRole("button", { name: "快速查询", exact: true }),
  ).toBeVisible();
});

test("人工画像保存新版本并默认锁定", async ({ page }) => {
  const state = await mockWorkspace(page);
  await page
    .getByRole("button", { name: fixture.song.title, exact: true })
    .click();
  await page.getByLabel("能量", { exact: true }).fill("0.1");
  await page.getByRole("button", { name: "保存人工画像", exact: true }).click();
  await expect(page.getByText("版本 2 · user", { exact: false })).toBeVisible();
  expect(state.profile().profile.energy).toBe(0.1);
  expect(state.profile().locked).toBe(true);
});

test("同名歌曲结合歌手识别位置", async ({ page }) => {
  await mockWorkspace(page, { sameTitle: true });
  await generate(page);
  await page
    .getByRole("button", { name: "交给 MoodMusic 播放", exact: true })
    .click();
  await expect(page.getByText("第 2 / 2 首", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "下一首", exact: true }),
  ).toBeDisabled();
});

test("手机上可以阅读推荐依据", async ({ page }) => {
  await mockWorkspace(page);
  await generate(page);
  await page
    .getByRole("button", { name: "为什么选中 · 画像 v1", exact: true })
    .first()
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect.poll(async () => (await dialog.boundingBox())?.width ?? Infinity).toBeLessThan(390);
  await expect(
    dialog.getByText("画像自评可信度 40 分，非实测准确率。", { exact: true }),
  ).toBeVisible();
});
