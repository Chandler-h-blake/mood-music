# QQ 音乐 PC 连接器

本目录记录 QQ 音乐 PC 22.41 的连接器可行性验证。客户端安装并注册了 `QQMusicSvr 1.0` COM 自动化协议，类型库公开歌曲队列、当前歌曲和播放控制等接口；但实机验证表明现代客户端播放时不会启动该服务，临时激活的 COM 实例始终是空队列，因此不能作为当前播放连接器。

只读探测：

```powershell
& .\scripts\probe-qqmusic-com.ps1
```

脚本从 Windows 注册表读取实际安装路径，使用系统自带的 32 位 .NET Framework 编译器构建临时探测程序，仅调用当前歌曲 ID、队列数量和队列 ID 查询。构建产物进入已被 Git 忽略的 `data/pc-connector`。若 COM 服务未运行，脚本会短暂以 `-Embedding` 启动它，并在探测结束后只停止本次启动的服务进程。

当服务不是由客户端预先启动时，脚本返回 `standaloneReadOnly`，明确区分“遗留服务能调用”和“当前播放器已接通”。2026-09-13 在 QQ 音乐正在播放时，客户端进程存在但 `QQMusicSvr` 不存在，临时服务返回当前歌曲和队列均为 0；COM 路线因此停止，不启用任何修改或播放方法。

Windows 系统媒体会话只读探测：

```powershell
& .\scripts\probe-windows-media-sessions.ps1
```

2026-09-13 实机已识别 `QQMusic.exe`、真实 `Playing` 状态、歌曲元数据、播放进度、总时长，以及暂停、上一首、下一首能力。探测器目前不调用任何控制方法；下一步将控制动作做成用户明确触发的单步测试。系统媒体会话不提供搜索和精确队列构造，这两项仍需独立解决。

基础控制：

```powershell
& .\scripts\control-qqmusic.ps1 -Action Play
& .\scripts\control-qqmusic.ps1 -Action Pause
& .\scripts\control-qqmusic.ps1 -Action Next
& .\scripts\control-qqmusic.ps1 -Action Previous
```

每次命令只操作唯一的 `QQMusic.exe` 媒体会话，并返回操作是否被系统接受及操作前后的状态。找不到会话、出现多个同名会话、目标能力未声明或 Windows 拒绝命令时都会报告 `rejected`。

2026-09-13 四项命令已完成实机验证：暂停后恢复播放成功；“下一首 → 上一首”从原曲切到下一首后正确返回原曲。系统媒体会话基础控制因此可声明 `playback.control`，搜索和精确队列仍未实现。
