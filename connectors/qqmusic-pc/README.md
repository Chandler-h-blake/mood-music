# QQ 音乐 PC 连接器

本目录记录 QQ 音乐 PC 22.41 的连接器验证。当前正式路线由 FastAPI 调用客户端自身的 `/playbysongid` 命令入口精确启动歌曲，并通过 Windows 系统媒体会话读取状态和执行基础控制。它不使用截图、OCR、坐标点击、键盘模拟、进程注入或内存读取。

本机安装同时注册了 `QQMusicSvr 1.0` COM 自动化协议；但实机验证表明现代客户端播放时不会启动该服务，临时激活的 COM 实例始终是空队列，因此 COM 只保留为兼容性诊断，不作为当前播放连接器。

只读探测：

```powershell
& .\scripts\probe-qqmusic-com.ps1
```

脚本从 Windows 注册表读取实际安装路径，使用系统自带的 32 位 .NET Framework 编译器构建临时探测程序，仅调用当前歌曲 ID、队列数量和队列 ID 查询。构建产物进入已被 Git 忽略的 `data/pc-connector`。若 COM 服务未运行，脚本会短暂以 `-Embedding` 启动它，并在探测结束后只停止本次启动的服务进程。

当服务不是由客户端预先启动时，脚本返回 `standaloneReadOnly`，明确区分“遗留服务能调用”和“当前播放器已接通”。2026-09-13 在 QQ 音乐正在播放时，客户端进程存在但 `QQMusicSvr` 不存在，临时服务返回当前歌曲和队列均为 0；COM 路线因此停止，不启用任何修改或播放方法。

另外两个只读诊断脚本可确认安装目录内 `QQMusicApi.dll` 的客户端版本接口，以及 `QQMusic_Protocol.dll` 的协议对象能否激活；它们不发送播放命令：

```powershell
& .\scripts\probe-qqmusic-api-client.ps1
& .\scripts\probe-qqmusic-protocol-activation.ps1
```

Windows 系统媒体会话只读探测：

```powershell
& .\scripts\probe-windows-media-sessions.ps1
```

2026-09-13 实机已识别 `QQMusic.exe`、真实 `Playing` 状态、歌曲元数据、播放进度、总时长，以及暂停、上一首、下一首能力。

基础控制：

```powershell
& .\scripts\control-qqmusic.ps1 -Action Play
& .\scripts\control-qqmusic.ps1 -Action Pause
& .\scripts\control-qqmusic.ps1 -Action Next
& .\scripts\control-qqmusic.ps1 -Action Previous
```

每次命令只操作唯一的 `QQMusic.exe` 媒体会话，并返回操作是否被系统接受及操作前后的状态。找不到会话、出现多个同名会话、目标能力未声明或 Windows 拒绝命令时都会报告 `rejected`。

2026-09-13 四项命令已完成实机验证：暂停后恢复播放成功；“下一首 → 上一首”从原曲切到下一首后正确返回原曲。

## 精确歌曲与临时队列

静态检查客户端安装文件发现 QQ 音乐 22.41 接受 `/playbysongid`，参数形如 `cmd_count==1&&id_0==数字歌曲ID&&songtype_0==0`。后端先把曲库保存的公开 song mid 批量解析为数字歌曲 ID，再用参数数组启动 `QQMusic.exe`，最后通过系统媒体状态回读标题确认结果。未经校验的字符串不会进入客户端命令。

网页的“在 QQ 音乐中播放”按钮调用 `POST /api/v1/playback/queues`。后端保存所选快照的顺序并启动第一首；之后 `POST /api/v1/playback/actions` 的 `next` 和 `previous` 会按 MoodMusic 队列精确点播，`play` 和 `pause` 继续使用 Windows 媒体 API。实机已验证 29 首队列启动，以及从第 1 首准确切换到第 2 首。

该命令是版本相关、未公开的客户端入口，升级 QQ 音乐后必须重新做兼容性验证。客户端自身不会可靠接收整张 MoodMusic 队列，因此“歌曲自然播放结束后自动切到 MoodMusic 下一首”和“最后一首停止”尚未完成；当前可靠范围是开始播放与用户触发的前后切歌。
