/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'crypto-bg': '#0a0a0f',
        'crypto-surface': '#13131a',
        'crypto-border': '#1e1e2e',
        'crypto-primary': '#6366f1',
        'crypto-success': '#22c55e',
        'crypto-warning': '#f59e0b',
        'crypto-danger': '#ef4444',
        'crypto-text': '#e4e4e7',
        'crypto-muted': '#71717a',
      },
    },
  },
  plugins: [],
}
