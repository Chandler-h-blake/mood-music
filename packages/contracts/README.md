# MoodMusic shared contracts

`schema/connector-message-v1.schema.json` 是 Chrome 与 QQ 音乐 PC 播放连接器共同使用的线协议。`@moodmusic/contracts` 从 `src/connector-v1.ts` 导出 TypeScript 消息类型与 `ConnectorAdapter` 接口，FastAPI 中的 `connector_protocol.py` 提供运行时 Pydantic 校验。

协议变更后运行：

```powershell
& "D:\Program\CondaEnvs\mood-music\python.exe" packages\contracts\generate_connector_schema.py
```

随后运行后端测试。测试会检查生成后的 JSON Schema 与 Pydantic 模型没有漂移。
