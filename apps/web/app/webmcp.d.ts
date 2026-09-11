type MoodMusicWebMcpTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: object;
  annotations?: {
    readOnlyHint?: boolean;
    untrustedContentHint?: boolean;
  };
  execute(input: unknown): unknown | Promise<unknown>;
};

type MoodMusicModelContext = {
  registerTool(
    tool: MoodMusicWebMcpTool,
    options?: { signal?: AbortSignal },
  ): void | Promise<void>;
};

declare global {
  interface Document {
    readonly modelContext?: MoodMusicModelContext;
  }
}

export {};
