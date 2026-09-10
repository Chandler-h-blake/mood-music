# 项目文档索引

本目录是 MoodMusic 的决策与交付基线。开始开发、评审需求或修改架构前，应从本页进入对应文档，避免 README、代码和口头约定彼此冲突。

## 文档优先级

发生冲突时按以下顺序处理：

1. 已接受的架构决策记录 ADR。
2. 当前系统设计。
3. 当前产品需求文档 PRD。
4. 数据模型、API 合约、安全与测试规范。
5. README 和其他说明。

发现冲突时不得静默选择其中一份继续开发。应先修改上位文档或新增 ADR，并在 `CHANGELOG.md` 记录影响。

## 产品与范围

- [产品需求文档](product/PRD.md)：目标用户、业务流程、功能需求、非功能需求和验收标准。
- [版本路线图](roadmap/ROADMAP.md)：工程阶段、退出条件和首版发布标准。

## 架构与决策

- [系统设计](architecture/SYSTEM_DESIGN.md)：运行组件、数据流、通信方式和失败隔离。
- [ADR 001 独立应用形态](architecture/ADR-001-independent-product.md)：为何从原生 QQ 音乐 Mod 转为独立应用。
- [ADR 002 QQ 音乐网页版播放连接器](architecture/ADR-002-qqmusic-web-connector.md)：为何使用浏览器扩展控制网页播放器。
- [ADR 003 手动 Cookie 音乐库同步](architecture/ADR-003-manual-cookie-library-sync.md)：为何首版由本机后端保管 Cookie 并只读同步“我喜欢”。

## 数据与接口

- [数据模型](data/DATA_MODEL.md)：实体、主键、来源、版本和保留策略。
- [API 合约](api/API_CONTRACT.md)：HTTP、SSE、WebSocket、错误格式和幂等规则。

## 工程与质量

- [开发指南](development/DEVELOPMENT_GUIDE.md)：分支、环境、迁移、提交和评审流程。
- [编码规范](development/CODING_STANDARDS.md)：跨语言命名、模块边界和代码质量规则。
- [安全与隐私](development/SECURITY_AND_PRIVACY.md)：密钥、QQ 登录态、音频和日志边界。
- [QQ 音乐兼容性记录](development/QQMUSIC_COMPATIBILITY.md)：真实接口验证范围、结果和当前限制。
- [测试策略](quality/TEST_STRATEGY.md)：测试层级、AI 评测集和发布门槛。

## 历史参考

上级目录中的 `QQ音乐AI选歌插件_产品与技术实施计划书.docx` 记录了最初的固定版本原生 Mod 方案。该文件只作为历史产品输入保留，不属于当前 Git 仓库，也不再控制当前系统架构。仍适用的业务规则已经迁移到当前 PRD；架构变化由 ADR 001 和 ADR 002 明确记录。
