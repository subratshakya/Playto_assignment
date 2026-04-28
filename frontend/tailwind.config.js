/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f4efe8",
        ink: "#1f1d1a",
        accent: "#d5643c",
        accentSoft: "#f0c5ad",
        pine: "#1f4b43",
        mist: "#fff9f2",
        line: "#dbcdbb",
      },
      boxShadow: {
        card: "0 24px 60px rgba(64, 39, 15, 0.12)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
      fontFamily: {
        display: ["Georgia", "Cambria", "Times New Roman", "serif"],
        body: ["'Segoe UI'", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
