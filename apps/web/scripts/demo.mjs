process.env.NEXT_PUBLIC_DEMO_MODE = "true";
process.argv = [process.execPath, new URL("./run-framework.mjs", import.meta.url).pathname, "dev"];
await import("./run-framework.mjs");
