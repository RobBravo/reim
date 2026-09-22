import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        reim: {
          bg: "#0f1720",
          surface: "#132234",
          surfaceElevated: "#1a2c42",
          border: "#1e293b",
          borderSubtle: "#162232",
          gold: "#e8b84b",
          goldHover: "#f5c75d",
          goldMuted: "rgba(232, 184, 75, 0.15)",
          text: "#f1f5f9",
          muted: "#94a3b8",
          subtle: "#64748b",
        },
      },
    },
  },
  plugins: [],
};
export default config;
