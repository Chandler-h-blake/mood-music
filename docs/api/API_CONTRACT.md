# MoodMusic API 与连接器契约

## 1 契约原则

MoodMusic 的 Web、API、后台 worker 和浏览器扩展只能通过版本化契约协作。实现前先确定 schema，再生成 TypeScript 与 Python 类型。任何不兼容变化必须增加主版本并提供迁移说明。

首期 HTTP 前缀为 `/api/v1`。所有 JSON 字段使用 `camelCase`，数据库与 Python 内部可以使用 `snake_case`，但转换必须集中在 schema 层。

本文同时记录当前实现和目标契约。未特别标注的条目属于目标契约；截至 2026-09-13，已实现范围为健康检查、QQ 音乐与 DeepSeek 凭据、曲库预览/同步/查询、画像任务创建/查询/重试、自然语言搜索、会话追加要求、三种排序、候选删除/拖动/找相似、临时队列历史/恢复、连接器协议描述与 HTTP 能力协商，以及 PC QQ 音乐的状态、基础控制、精确启动队列第一首和后端顺序前后切歌。PC 遗留 COM 实机已证明未接通现代客户端。版本、通用设置修改、导入批次、单曲画像覆盖、暂停/取消/SSE、自动续播与末曲停止、连接器实时传输、外部发现和队列导出仍是计划接口。

## 2 通用约定

### 请求头

| 请求头 | 用途 |
| --- | --- |
| `X-Request-Id` | 调用方生成的 UUID；缺失时服务端生成 |
| `Idempotency-Key` | 导入、任务创建、队列提交等可重试写操作必填 |
| `Content-Type` | JSON 请求使用 `application/json` |

### 通用错误

```json
{
  "error": {
    "code": "connector.offline",
    "message": "QQ 音乐播放连接器当前不在线",
    "requestId": "0c50145d-66a6-4e71-8e18-d1c24f2d13fd",
    "details": {
      "requiredCapability": "queue.play"
    }
  }
}
```

错误码使用稳定的 `domain.reason`，用户消息使用中文，`details` 不得包含密钥、Cookie、受保护 URL 或第三方原始响应全文。

## 3 HTTP 资源

### 健康与版本

- `GET /api/v1/health`：API 进程健康状态。
- `GET /api/v1/health/ready`：API 与 PostgreSQL 就绪状态。
- `GET /api/v1/version`：应用版本、schema 版本和支持的连接器协议范围。

### 设置与提供方

- `GET /api/v1/settings`：返回去敏配置和密钥是否已设置。
- `PATCH /api/v1/settings`：更新非敏感配置。
- `PUT /api/v1/credentials/{provider}`：把密钥写入操作系统凭据存储。
- `DELETE /api/v1/credentials/{provider}`：删除密钥。
- `POST /api/v1/providers/{provider}/test`：测试模型、搜索或 QQ 音乐登录连接。

`provider=qqmusic-cookie` 时，`PUT` 请求接收用户主动粘贴的 Cookie，`POST /api/v1/providers/qqmusic-cookie/test` 验证 QQ 音乐登录状态，`DELETE` 清除本机 Cookie。Cookie 与模型密钥使用独立凭据名称。

`provider=deepseek` 时，`PUT` 保存独立的 DeepSeek API Key，`POST /api/v1/providers/deepseek/test` 同时验证凭据与结构化意图输出。Embedding 由本地 BGE-M3 提供，不接收云端密钥。

凭据写入响应只返回凭据引用 ID、`configured`、验证状态、可确定的过期时间和掩码信息，永远不返回原值。Cookie 请求体不得进入访问日志或错误监控。

### 音乐库

- `POST /api/v1/library/imports`：创建手动或连接器导入批次。
- `GET /api/v1/library/imports/{importId}`：读取统计、游标和错误。
- `GET /api/v1/library/songs`：分页读取喜欢歌曲与画像状态；支持可选 `q` 参数按歌曲名、歌手或专辑搜索。
- `GET /api/v1/library/songs/{songId}`：读取歌曲、当前画像和人工覆盖。
- `PATCH /api/v1/library/songs/{songId}/overrides`：修改并锁定画像字段。
- `POST /api/v1/library/sync`：顺序读取 QQ 音乐“我喜欢”全部分页并原子更新本地数据库；当前阶段等待同步完成后返回 `200`，后台任务化后再升级为 `202`。凭据只由服务端凭据代理读取。
- `POST /api/v1/library/sync-preview`：在数据库接入前只读获取“我喜欢”第一页，用于验证当前 Cookie 与字段映射；响应标记 `diagnosticOnly=true`，不持久化数据。

导入示例：

```json
{
  "source": "qqmusic-cookie-sync",
  "connectorInstallationId": null,
  "cursor": null,
  "songs": [
    {
      "provider": "qqmusic",
      "sourceTrackId": "platform-track-id",
      "title": "示例歌曲",
      "artists": [{"name": "示例歌手"}],
      "album": null,
      "durationMs": null
    }
  ]
}
```

完整同步响应包含 `runId`、`status`、`pagesFetched`、`reportedTotal`、`fetchedCount`、`uniqueCount`、`insertedCount`、`updatedCount`、`deactivatedCount` 和 `skippedMissingId`。任何页面失败或完整性校验失败时，不修改最近一次成功的成员关系。

### 画像任务

当前实现以 `incremental` 为默认模式，按环境变量 `PROFILE_BATCH_SIZE` 分批持久化；每个成功批次更新 checkpoint。`rebuild` 会追加画像版本，不原地覆盖旧版本。当前进程内执行器支持失败后重试，暂停、取消、SSE 与进程启动时自动恢复留在后续任务生命周期迭代。

- `POST /api/v1/profile-jobs`：创建初始化或增量画像任务。
- `GET /api/v1/jobs/{jobId}`：读取状态、进度和失败分类。
- `POST /api/v1/jobs/{jobId}/pause`：请求在安全 checkpoint 暂停。
- `POST /api/v1/jobs/{jobId}/resume`：继续任务。
- `POST /api/v1/jobs/{jobId}/cancel`：请求取消。
- `POST /api/v1/jobs/{jobId}/retry`：重试可恢复失败。
- `GET /api/v1/jobs/{jobId}/events`：SSE 任务事件。

任务创建响应使用 `202 Accepted`，返回 `jobId` 与事件地址。

### 搜索会话

当前实现使用结构化意图、同一 Embedding 模型空间中的原始非负余弦相似度与可用连续特征进行均衡评分，并对明确的悲伤、紧张、能量上限、排除流派、人声模式、演唱语言和纯音乐许可执行硬边界。自由文本画像标签会先在本地归一化为稳定代码，例如 `mixed_duet`、`instrumental`、`zh` 与 `en`，无需重新画像。只有用户原文明确表达的情绪或能量边界才会成为硬约束。均衡模式门槛不低于 0.75。所有当前喜欢且画像可用的歌曲均被评估并留下候选审计记录；响应不做固定 Top-K 截断。

- `POST /api/v1/search-sessions`：创建自然语言搜索。
- `GET /api/v1/search-sessions/{sessionId}`：读取意图、状态和候选集合。
- `GET /api/v1/search-sessions/{sessionId}/events`：SSE 搜索进度。
- `POST /api/v1/search-sessions/{sessionId}/refinements`：追加会话要求。
- `DELETE /api/v1/search-sessions/{sessionId}/candidates/{candidateId}`：从当前会话删除候选。
- `PATCH /api/v1/search-sessions/{sessionId}/candidate-order`：保存拖动结果。
- `POST /api/v1/search-sessions/{sessionId}/sorts`：对同一候选集合执行排序。
- `POST /api/v1/search-sessions/{sessionId}/candidates/{candidateId}/similar`：保持候选集合不变，以指定歌曲为基准重排。

创建搜索示例：

```json
{
  "description": "凌晨开车时有一点孤独，但不要太悲伤",
  "matchingPolicy": "balanced",
  "sortMode": "match",
  "library": "liked"
}
```

排序请求：

```json
{
  "mode": "emotionCurve",
  "curve": {
    "start": "calm",
    "middle": "slightlyLifted",
    "end": "settled"
  },
  "randomSeed": null
}
```

允许的模式为 `match`、`emotionCurve` 和 `random`。排序响应必须返回同一 `candidateSetHash`，否则客户端拒绝应用。

### 队列与播放列表

- `POST /api/v1/generated-playlists`：从搜索会话保存临时队列快照。
- `GET /api/v1/generated-playlists/{playlistId}`：读取快照、排序和保存状态。
- `GET /api/v1/generated-playlists`：分页读取队列快照历史。
- `POST /api/v1/generated-playlists/{playlistId}/restore`：把历史候选集合与顺序恢复为新的可编辑快照。
- `POST /api/v1/playback/queues`：接收 `playlistId`，读取已持久化快照，把 song mid 映射为客户端数字 ID，精确启动第一首并在后端保存队列顺序；已实现。
- `GET /api/v1/playback/state`：通过 Windows 系统媒体 API 读取 QQ 音乐当前状态、歌曲、进度和基础能力；已实现。
- `POST /api/v1/playback/actions`：`play`、`pause` 使用 Windows 系统媒体 API；存在活动 MoodMusic 队列时，`next`、`previous` 按后端队列精确点播，否则回退到系统媒体控制。已实现并区分“已观察到完成”与“仅被系统接收”。
- `GET /api/v1/playback/events`：SSE 播放状态。
- `POST /api/v1/generated-playlists/{playlistId}/exports`：导出可恢复的 JSON、CSV 或 M3U 清单；不写入 QQ 音乐账号。

当前 HTTP 请求只接收 `playlistId`，`snapshotHash` 和按顺序排列的 `sourceTrackId` 从不可变的数据库快照读取，避免前端篡改队列内容。未来外部歌曲进入队列时必须带 `source=external` 和用户明确加入的审计事件。

当前 PC HTTP API 不通过截图、OCR、坐标点击或键盘输入操纵 QQ 音乐。它使用 QQ 音乐 22.41 自身的 `/playbysongid` 命令精确点播，并以 Windows 系统媒体 API 回读确认。该入口没有公开稳定性保证，因此客户端升级后必须重新验证。客户端原生整队列写入尚未证明可靠，当前由后端维护顺序；自动续播和最后一首停止尚未实现。

### 外部发现

- `POST /api/v1/external-discovery-jobs`：按搜索会话、候选集合或歌曲创建任务。
- `GET /api/v1/external-discovery-jobs/{jobId}`：读取校验通过的建议。
- `POST /api/v1/external-suggestions/{suggestionId}/actions`：试听、在 QQ 音乐中打开、手动入队或不感兴趣；“加入喜欢”由用户在 QQ 音乐页面执行。

未校验结果只用于内部诊断，不在普通响应中返回。

## 4 SSE 事件

事件类型：

- `job.progress`
- `job.paused`
- `job.completed`
- `job.failed`
- `search.stageChanged`
- `search.completed`
- `connector.statusChanged`
- `qqmusic.authenticationChanged`
- `playback.stateChanged`

示例：

```text
event: job.progress
id: 148
data: {"jobId":"...","completed":420,"total":1087,"failed":3}
```

客户端断线重连时发送 `Last-Event-ID`。服务端保留足以恢复当前任务的事件游标，但数据库实体状态始终是真实来源。

## 5 连接器本机协议

连接地址只绑定本机，例如 `ws://127.0.0.1:{port}/connector/v1`。Chrome 扩展使用 WebSocket；PC 本地助手可以使用同一 WebSocket 或具有相同消息 schema 的受限本机传输。第一次连接使用短时配对代码，成功后换取可撤销令牌。

当前已实现 `GET /api/v1/connectors/protocol` 用于读取版本、类型、能力和消息清单，`POST /api/v1/connectors/negotiate` 用于对 `connector.hello` 执行无状态合约与能力协商。它们是适配器开发和诊断入口，不代表连接器已经在线或已完成安全配对；实时 WebSocket、令牌和连接状态持久化将在下一迭代实现。

### 消息信封

```json
{
  "protocolVersion": "1.0",
  "type": "playback.queueRequested",
  "requestId": "aa286865-1a76-4bfe-99fa-6358f2c37387",
  "sentAt": "2026-09-08T10:00:00Z",
  "payload": {}
}
```

### 核心消息

- `connector.hello`：连接器类型、连接器版本、目标应用版本、适配器版本和能力。
- `connector.heartbeat`：活跃页面和连接状态。
- `catalog.searchRequested` / `catalog.searchCompleted`。
- `playback.queueRequested` / `playback.queueAccepted` / `playback.queueRejected`。
- `playback.actionRequested` / `playback.stateChanged`。

### 能力名称

- `catalog.search`
- `queue.play`
- `playback.control`
- `playback.state`

能力未声明时，API 不得下发相应命令。

## 6 合约演进

- OpenAPI 是 HTTP 契约的唯一机器可读来源。
- JSON Schema 是连接器消息的唯一机器可读来源。
- `packages/contracts` 保存 schema、生成脚本和 TypeScript 产物；Python 模型从相同 schema 生成或进行一致性测试。
- CI 检查破坏性变化、生成文件漂移和示例有效性。
- 契约变化必须更新本文件、CHANGELOG、测试和对应 ADR。
