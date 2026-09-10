# 变更记录

本文件记录会影响用户、数据、接口、部署或兼容性的变化。格式参考 Keep a Changelog，版本遵循语义化版本。

## Unreleased

### Changed

- 将手动粘贴 QQ 音乐 Cookie 确认为首版正式登录方案；Cookie 由 Windows 凭据存储或 DPAPI 保护，只供本机只读同步使用。
- 将 QQ 音乐接入拆分为 Python 只读数据适配器和 Manifest V3 网页播放连接器；二维码登录留作后续评估。
- 明确禁止 QQ 音乐写操作、音频直链、代理、下载、缓存和解密进入首版范围。

### Added

- 建立产品、架构、数据、接口、质量和开发规范文档。
- 建立 Web、API、浏览器扩展、共享契约、基础设施和端到端测试目录。
- 确定独立 Web 应用与 QQ 音乐网页版连接器的目标形态。
- 建立首个可运行的 FastAPI 纵向切片：Windows 凭据存储中的 QQ 音乐 Cookie、登录验证和“我喜欢”第一页只读预览。
- 使用 Windows DPAPI 加密文件保存长 Cookie，避免 Credential Manager 单条凭据容量限制导致保存失败。
- 允许开发进程通过 `MOODMUSIC_DATA_DIR` 把 DPAPI 密文写入 Git 忽略的数据目录，避免受控开发环境阻止标准用户目录写入。
- 增加 PostgreSQL 16 + pgvector Docker Compose、本地健康检查和 Alembic 首版音乐库迁移。
- 增加 QQ 音乐“我喜欢”自动全分页、完整性保护、平台 ID 去重与缺失 ID 稳定哈希回退。
- 增加原子增量同步批次、歌曲与喜欢成员关系持久化，以及本地曲库分页查询 API。
