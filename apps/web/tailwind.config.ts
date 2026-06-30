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
        glow: "0 0 0 1px rgba(255,255,255,0.08), 0 24px 80px rgba(0,0,0,0.9)",
        "glow-lg": "0 0 60px rgba(255,255,255,0.06), 0 0 0 1px rgba(255,255,255,0.1)"
      },
      animation: {
        "float": "float 4s ease-in-out infinite",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scroll-left": "scroll-left 20s linear infinite",
        "slide-up": "slide-up 0.5s ease-out forwards",
        "wave": "wave 1.5s ease-in-out infinite",
        "shimmer": "shimmer 3s ease-in-out infinite",
        "glow-pulse": "glow-pulse 3s ease-in-out infinite",
        "travel": "travel 2.5s linear infinite",
        "fade-in-up": "fade-in-up 0.7s ease-out forwards",
        "typing": "typing 3s steps(40) infinite alternate",
        "blink": "blink 1s step-end infinite",
        "bounce-arrow": "bounce-arrow 2s ease-in-out infinite",
        "spin-slow": "spin 8s linear infinite",
        "grid-drift": "grid-drift 15s linear infinite",
        "node-pulse": "node-pulse 2s ease-in-out infinite",
        "stagger-fade": "fade-in-up 0.5s ease-out forwards"
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
        },
        "shimmer": {
          "0%": { backgroundPosition: "-200% center" },
          "100%": { backgroundPosition: "200% center" }
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 20px rgba(255,255,255,0.04), 0 0 0 1px rgba(255,255,255,0.08)" },
          "50%": { boxShadow: "0 0 40px rgba(255,255,255,0.08), 0 0 0 1px rgba(255,255,255,0.15)" }
        },
        "travel": {
          "0%": { left: "-5%", opacity: "0" },
          "10%": { opacity: "1" },
          "90%": { opacity: "1" },
          "100%": { left: "100%", opacity: "0" }
        },
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(32px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "typing": {
          "0%": { maxWidth: "0" },
          "100%": { maxWidth: "100%" }
        },
        "blink": {
          "0%, 100%": { borderColor: "rgba(255,255,255,0.6)" },
          "50%": { borderColor: "transparent" }
        },
        "bounce-arrow": {
          "0%, 100%": { transform: "translateY(0)", opacity: "0.4" },
          "50%": { transform: "translateY(8px)", opacity: "1" }
        },
        "grid-drift": {
          "0%": { backgroundPosition: "0 0" },
          "100%": { backgroundPosition: "64px 64px" }
        },
        "node-pulse": {
          "0%, 100%": { transform: "scale(1)", opacity: "0.8" },
          "50%": { transform: "scale(1.08)", opacity: "1" }
        }
      }
    }
  },
  plugins: []
};

export default config;
