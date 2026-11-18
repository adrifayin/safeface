/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // System fonts only: no web-font download.
        sans: ["system-ui", "Segoe UI", "Roboto", "Noto Sans", "Noto Sans Malayalam", "sans-serif"],
        mono: ["ui-monospace", "Consolas", "DejaVu Sans Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
