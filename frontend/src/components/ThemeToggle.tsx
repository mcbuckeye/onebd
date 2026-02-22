import { useEffect } from 'react';

export default function ThemeToggle() {
  const root = document.documentElement;
  
  // Initialize theme from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark') {
      root.classList.add('dark-mode');
    } else {
      root.classList.remove('dark-mode');
    }
  }, [root]);

  const toggle = () => {
    const isDark = root.classList.toggle('dark-mode');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  };

  return (
    <button
      onClick={toggle}
      className="p-1 rounded hover:bg-slate-800"
      aria-label="Toggle dark mode"
    >
      {/* Simple sun/moon icons using Unicode */}
      {root.classList.contains('dark-mode') ? '🌙' : '☀️'}
    </button>
  );
}
