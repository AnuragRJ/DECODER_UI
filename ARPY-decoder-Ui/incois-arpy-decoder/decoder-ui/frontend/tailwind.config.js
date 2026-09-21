/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        argo: {
          950: "#061224",
          900: "#0c1e3d",
          850: "#102852",
          800: "#163469",
          700: "#1e498f",
          600: "#2563eb",
          500: "#3b82f6",
          400: "#60a5fa",
          300: "#93c5fd",
          200: "#bfdbfe",
          100: "#dbeafe",
          50: "#eff6ff",
        },
        ocean: {
          dark: "#0b1528",
          card: "#13233f",
          border: "#1f3760",
          accent: "#00d2ff",
          yellow: "#eab308",
          emerald: "#10b981",
          rose: "#ef4444",
        },
      },
      animation: {
        "spin-slow": "spin 8s linear infinite",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-fast": "pulse 1s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "flow-dash": "flowDash 1s linear infinite",
      },
      keyframes: {
        flowDash: {
          "0%": { strokeDashoffset: "24" },
          "100%": { strokeDashoffset: "0" },
        },
      },
    },
  },
  plugins: [],
};
