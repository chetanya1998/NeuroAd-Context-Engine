import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#000000",
        card: "#050505",
        surface: "#0A0A0A",
        border: "#202020",
        primary: "#F8FAFC",
        cyan: "#E5E7EB",
        success: "#22C55E",
        warning: "#F59E0B",
        danger: "#EF4444"
      },
      fontFamily: {
        sans: ["Inter", "Manrope", "ui-sans-serif", "system-ui", "sans-serif"]
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(255,255,255,0.08), 0 24px 80px rgba(0,0,0,0.9)"
      },
      animation: {
        "float": "float 4s ease-in-out infinite",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scroll-left": "scroll-left 20s linear infinite",
        "slide-up": "slide-up 0.5s ease-out forwards",
        "wave": "wave 1.5s ease-in-out infinite"
      },
      keyframes: {
        "float": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" }
        },
        "scroll-left": {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" }
        },
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "wave": {
          "0%, 100%": { height: "20%" },
          "50%": { height: "80%" }
        }
      }
    }
  },
  plugins: []
};

export default config;
