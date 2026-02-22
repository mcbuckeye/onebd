import { useEffect } from 'react';

export default function ThemeToggle() {
  // Initialize theme from localStorage (Treat as "system" preference)
  useEffect(() => {
    const saved = localStorage.getItem('theme');
    // If saved as 'light', remove dark class; if 'dark' or not set, keep dark class (current default)
    if (saved === 'light') {
      document.documentElement.classList.remove('dark');
    } else {
      document.documentElement.classList.add('dark');
    }
  }, []);

  const toggle = () => {
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  };

  return (
    <button
      onClick={toggle}
      className="p-1 rounded hover:bg-slate-800 dark:hover:bg-slate-700 transition-colors"
      aria-label="Toggle theme"
    >
      {document.documentElement.classList.contains('dark') ? '🌙' : '☀️'}
    </button>
  );
}
