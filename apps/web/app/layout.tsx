import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MoodMusic · 我的音乐工作台",
  description: "从你的 QQ 音乐收藏中重新发现想听的歌。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
