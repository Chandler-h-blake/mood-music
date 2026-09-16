# MoodMusic · 用一句话找到此刻想听的歌

[![License: MIT](https://img.shields.io/badge/License-MIT-29e68b.svg)](LICENSE)
[![CI](https://github.com/Chandler-h-blake/mood-music/actions/workflows/ci.yml/badge.svg)](https://github.com/Chandler-h-blake/mood-music/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB.svg)](services/api/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-%E2%89%A522.13-339933.svg)](apps/web/package.json)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](docs/development/DEVELOPMENT_GUIDE.md)

![MoodMusic social preview](docs/assets/moodmusic-social-preview.png)

比如输入：

> 凌晨一个人开车，有一点孤独，但不要太悲伤。

MoodMusic 会从你的 QQ 音乐“喜欢”列表中找到符合这种感觉的歌曲，组成一份可以继续调整和播放的临时歌单。

想先看看效果？演示模式不需要 QQ 音乐账号、Cookie、模型密钥、Python 或 Docker，也不会上传任何数据。

[English README](README.en.md)

## 同学试玩：下载后双击即可

目前推荐使用 Windows 10 或 Windows 11。

1. 安装 [Node.js LTS](https://nodejs.org/en/download)。安装时保持默认选项即可；已经安装过可跳过。
2. 点击 GitHub 页面右上方绿色的 **Code → Download ZIP**，下载并解压项目。
3. 打开解压后的文件夹，双击 **`Start-MoodMusic-Demo.cmd`**。

第一次启动需要联网下载演示组件，通常会等待几分钟。准备完成后，浏览器会自动打开 MoodMusic。

试玩结束后，双击 **`Stop-MoodMusic.cmd`** 即可停止。以后再次启动仍然双击 `Start-MoodMusic-Demo.cmd`，不需要重复安装。

如果你习惯使用 PowerShell，也可以在项目目录运行：

```powershell
.\scripts\start-demo.ps1
```

## 演示模式里能体验什么

![MoodMusic 零配置演示界面](docs/assets/moodmusic-demo.png)

- 浏览一份虚构的“我喜欢”曲库。
- 用自然语言描述想听的感觉。
- 查看并调整 AI 生成的候选队列。
- 切换匹配度、情绪曲线和随机排序。
- 删除、拖动歌曲并恢复历史队列。
- 体验播放控制界面。

演示模式使用项目自带的虚构歌曲，不会连接 QQ 音乐，也不会调用付费模型。演示中的播放按钮只展示交互效果，不会播放真实音频。

## 使用自己的 QQ 音乐曲库（进阶）

完整模式适合愿意继续配置本机环境的用户。它目前需要：

- Windows 10/11 与 QQ 音乐桌面客户端
- Python 3.12 或 3.13
- Node.js 22.13 或更高版本
- Docker Desktop
- 可用的模型 API Key

在 PowerShell 中依次运行：

```powershell
.\scripts\setup.ps1
.\scripts\doctor.ps1
.\scripts\start.ps1
```

然后打开 `http://127.0.0.1:5173`，按页面中的“同步曲库 → 模型设置 → 更新全部画像 → AI 选歌”完成配置。停止程序时运行：

```powershell
.\scripts\stop.ps1
```

完整模式可以只读同步当前账号的“我喜欢”，用模型建立歌曲画像并理解自然语言需求，再把确认后的队列交给本机 QQ 音乐客户端。QQ 音乐仍负责音频解码和播放，MoodMusic 不下载音频，也不获取受保护的音频地址。

> 完整模式涉及 QQ 音乐 Cookie、模型服务和本机播放连接器，更适合项目展示或技术体验。只是想看看产品效果的同学，请直接使用上面的一键演示模式。

## 隐私与安全

- MoodMusic 不需要、也不会保存你的 QQ 密码。
- QQ 音乐 Cookie 和模型密钥由当前 Windows 用户的系统凭据保护，不写入 Git、数据库或浏览器持久化。
- 本机服务默认只监听 `127.0.0.1`，不会主动暴露到局域网或互联网。
- 主选歌结果只来自用户自己的“喜欢”列表；外部推荐不会偷偷混入。
- 项目不修改 QQ 音乐安装文件，不绕过会员、地区、版权或 DRM 限制。

请不要把真实 Cookie 或 API Key 粘贴到源码、`.env`、终端命令、Issue、提交信息或聊天中。

## 常见问题

### 双击后提示没有 Node.js

安装 [Node.js LTS](https://nodejs.org/en/download)，安装完成后关闭提示窗口，再双击启动文件。

### 第一次启动为什么比较慢

首次运行需要下载前端依赖，速度取决于网络。后续启动会直接使用已经安装好的组件。

### 关闭浏览器后程序还在吗

还在。双击 `Stop-MoodMusic.cmd` 才会停止本机演示服务。

### 演示模式会影响我的 QQ 音乐吗

不会。它使用虚构数据，不读取账号、不控制 QQ 音乐，也不产生模型费用。

## 开发者入口

普通试玩不需要阅读下面这些资料。希望了解实现、参与开发或提交改进时，可查看：

- [贡献指南](CONTRIBUTING.md)
- [开发环境与命令](docs/development/DEVELOPMENT_GUIDE.md)
- [编码规范](docs/development/CODING_STANDARDS.md)
- [完整文档索引](docs/INDEX.md)
- [安全政策](SECURITY.md)
- [项目路线图](docs/roadmap/ROADMAP.md)

运行完整检查：

```powershell
.\scripts\test.ps1
```

## 开源许可与平台声明

MoodMusic 依据 [MIT License](LICENSE) 开放源代码，允许自由使用、修改与再分发。项目由 Tian Xuanhao（Chandler）开发，与腾讯或 QQ 音乐不存在隶属、赞助或官方认可关系。使用者仍须遵守适用的平台条款、内容授权、隐私要求和法律法规。
