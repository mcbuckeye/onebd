import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

interface KeyboardShortcutOptions {
  onFocusSearch?: () => void;
  onEscape?: () => void;
}

export function useKeyboardShortcuts(options: KeyboardShortcutOptions = {}) {
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is typing in an input/textarea
      const target = e.target as HTMLElement;
      const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
      
      // Focus search with / or Cmd+K
      if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && !isInput) {
        e.preventDefault();
        options.onFocusSearch?.();
        return;
      }

      // Escape to close modals/dropdowns
      if (e.key === 'Escape') {
        options.onEscape?.();
        // Also blur any focused element
        (document.activeElement as HTMLElement)?.blur();
        return;
      }

      // Navigation shortcuts (g + letter)
      // We track the 'g' key press and wait for the next key
      if (e.key === 'g' && !isInput) {
        e.preventDefault();
        
        // Add a one-time listener for the next key
        const handleNextKey = (nextEvent: KeyboardEvent) => {
          switch (nextEvent.key) {
            case 'd':
              navigate('/');
              break;
            case 's':
              navigate('/search');
              break;
            case 'a':
              navigate('/analytics');
              break;
            case 'c':
              navigate('/chat');
              break;
          }
          document.removeEventListener('keydown', handleNextKey);
        };
        
        document.addEventListener('keydown', handleNextKey, { once: true });
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [navigate, options]);
}
