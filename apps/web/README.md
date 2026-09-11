# MoodMusic Web

MoodMusic 的本机 Web 界面，使用 Next.js 16、React 19、TypeScript 和 Tailwind CSS。当前页面连接本机 FastAPI，支持浏览、分页、搜索并同步 QQ 音乐“我喜欢”。

## 启动

先确保根目录的 PostgreSQL 与 `services/api` 已启动，然后运行：

```powershell
Set-Location apps\web
npm install
npm run dev
```

开发地址默认为 `http://localhost:5173`，API 默认为 `http://127.0.0.1:8000`。如需修改 API 地址，设置 `NEXT_PUBLIC_API_URL`。

## 检查

```powershell
npm run lint
npm run build
```

Cookie、真实歌曲数据和模型 API Key 不进入前端代码或浏览器持久化。
