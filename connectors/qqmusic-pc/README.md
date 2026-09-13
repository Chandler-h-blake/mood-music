# QQ 音乐 PC 连接器

当前主路线验证 QQ 音乐 22.41 随客户端安装并注册到 Windows 的 `QQMusicSvr 1.0` COM 自动化协议。类型库公开歌曲队列、当前歌曲、播放、暂停、上一首、下一首和播放事件等接口。该接口没有面向个人开发者的稳定文档，因此所有能力都按客户端版本逐项探测并默认关闭。

只读探测：

```powershell
& .\scripts\probe-qqmusic-com.ps1
```

脚本从 Windows 注册表读取实际安装路径，使用系统自带的 32 位 .NET Framework 编译器构建临时探测程序，仅调用当前歌曲 ID、队列数量和队列 ID 查询。构建产物进入已被 Git 忽略的 `data/pc-connector`。若 COM 服务未运行，脚本会短暂以 `-Embedding` 启动它，并在探测结束后只停止本次启动的服务进程。

2026-09-13 实机结果为 `readOnlyReady`：COM 激活及三项查询全部成功。当前只完成安全读取，不启用 `AddSong`、`DeleteSong`、`SetPlaySequence`、`Play` 或其他修改/播放方法；下一步是用非私人测试队列逐项验证“加歌 → 定序 → 播放 → 状态回传”。
