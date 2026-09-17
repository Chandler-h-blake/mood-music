# MoodMusic · AI 驱动的个人音乐库选歌工具

[![License: MIT](https://img.shields.io/badge/License-MIT-29e68b.svg)](LICENSE)
[![CI](https://github.com/Chandler-h-blake/mood-music/actions/workflows/ci.yml/badge.svg)](https://github.com/Chandler-h-blake/mood-music/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB.svg)](services/api/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-%E2%89%A522.13-339933.svg)](apps/web/package.json)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](docs/development/DEVELOPMENT_GUIDE.md)

![MoodMusic social preview](docs/assets/moodmusic-social-preview.png)

MoodMusic 使用自然语言理解听歌需求，从用户自己的 QQ 音乐“喜欢”列表中生成可预览、可调整、可播放的临时队列。

> 凌晨一个人开车，有一点孤独，但不要太悲伤。

相比语言、流派或年代等固定筛选条件，MoodMusic 更关注完整的情绪、场景、强弱与排除条件，帮助用户重新发现个人曲库中已经收藏却很少播放的歌曲。

[English README](README.en.md)

## 核心功能

- 只读同步当前 QQ 音乐账号的“我喜欢”曲库。
- 使用多维画像描述歌曲，并保留字段来源、置信度与未知值。
- 解析自然语言中的情绪、场景、强度、排除项和排序趋势。
- 结合语义检索与全量候选评分，不使用固定 Top-K 截断结果。
- 支持匹配度、情绪曲线和随机三种排序方式。
- 支持候选删除、拖动排序、追加要求与历史队列恢复。
- 通过本机连接器控制 QQ 音乐桌面客户端播放确认后的队列。
- 使用 Windows 凭据保护 QQ 音乐 Cookie 与模型密钥。

## 安装与运行

MoodMusic 会在本机启动 Web 应用、API 服务和 PostgreSQL，支持同步真实曲库、建立歌曲画像、AI 选歌和播放控制。

### 环境要求

- Windows 10 或 Windows 11
- Python 3.12 或 3.13
- Node.js 22.13 或更高版本
- Docker Desktop
- QQ 音乐桌面客户端
- 可用的模型 API Key

获取源码并进入项目目录：

```powershell
git clone https://github.com/Chandler-h-blake/mood-music.git
cd mood-music
```

安装依赖、检查环境并启动：

```powershell
.\scripts\setup.ps1
.\scripts\doctor.ps1
.\scripts\start.ps1
```

启动完成后访问：

- Web 应用：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8000/docs`

在 Web 设置页中配置本机凭据，然后按照“同步曲库 → 模型设置 → 更新全部画像 → AI 选歌”的流程使用。

停止应用：

```powershell
.\scripts\stop.ps1
```

## 技术架构

| 模块 | 技术 |
| --- | --- |
| Web | Next.js、React、TypeScript |
| API | Python、FastAPI、Pydantic |
| 数据 | PostgreSQL、pgvector、SQLAlchemy、Alembic |
| AI | 可配置聊天模型、BGE-M3 Embedding |
| 播放 | Windows 本机连接器、QQ 音乐桌面客户端 |
| 质量 | pytest、ESLint、TypeScript、GitHub Actions |

MoodMusic 只负责曲库管理、选歌和队列控制。QQ 音乐客户端继续负责合规的音频解码与输出，项目不下载或转发音频。

## 隐私与安全

- 不读取或保存 QQ 密码。
- QQ 音乐 Cookie 与模型密钥保存在当前 Windows 用户可解密的系统凭据存储中。
- 凭据不会写入业务数据库、Git、日志或浏览器持久化。
- 本机 API 默认只监听 `127.0.0.1`。
- 不修改或注入 QQ 音乐安装文件。
- 不提供绕过会员、地区、版权或 DRM 限制的功能。

请勿将真实 Cookie、Token 或 API Key 写入源码、`.env`、Issue、提交信息或聊天内容。

## 开发与文档

```powershell
.\scripts\test.ps1
```

完整检查包括 Ruff、pytest、ESLint、TypeScript 类型检查、生产构建与生产依赖审计。

- [贡献指南](CONTRIBUTING.md)
- [开发指南](docs/development/DEVELOPMENT_GUIDE.md)
- [编码规范](docs/development/CODING_STANDARDS.md)
- [文档索引](docs/INDEX.md)
- [项目路线图](docs/roadmap/ROADMAP.md)
- [安全政策](SECURITY.md)

## 开源许可

MoodMusic 依据 [MIT License](LICENSE) 开放源代码，允许自由使用、修改与再分发。

本项目由 Tian Xuanhao（Chandler）开发，与腾讯或 QQ 音乐不存在隶属、赞助或官方认可关系。QQ 音乐及相关标识归其权利人所有。
