import { useState, useRef } from 'react';
import { Outlet, NavLink, useNavigate, Navigate } from 'react-router-dom';
import {
  LayoutDashboard, Search, BarChart3, Building2,
  Network, FileText, ScrollText, Star, MessageSquare,
  Menu, LogOut, ChevronLeft, Scale, Shield, HelpCircle,
  Users, Brain, Settings, CalendarDays
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import ThemeToggle from '../components/ThemeToggle';
import NotificationDropdown from '../components/NotificationDropdown';

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/search', icon: Search, label: 'Search' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/catalysts', icon: CalendarDays, label: 'Catalysts' },
  { to: '/competitors', icon: Building2, label: 'Competitors' },
  { to: '/graph', icon: Network, label: 'Network' },
  { to: '/filings', icon: FileText, label: 'Filings' },
  { to: '/contracts', icon: ScrollText, label: 'Contracts' },
  { to: '/my-deals', icon: Star, label: 'My Deals' },
  { to: '/comps', icon: Scale, label: 'Comps' },
  { to: '/dd', icon: Shield, label: 'Due Diligence' },
  { to: '/agentic-rag', icon: Brain, label: 'Agentic RAG' },
  { to: '/chat', icon: MessageSquare, label: 'Ask' },
];

export default function MainLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [askQuery, setAskQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Setup keyboard shortcuts
  useKeyboardShortcuts({
    onFocusSearch: () => searchInputRef.current?.focus(),
    onEscape: () => setMobileOpen(false),
  });

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (askQuery.trim()) {
      navigate(`/chat?q=${encodeURIComponent(askQuery.trim())}`);
      setAskQuery('');
    }
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 bg-black/50 z-30" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed lg:relative inset-y-0 left-0 z-40
        flex flex-col bg-slate-900 border-r border-slate-800
        transition-all duration-200
        ${sidebarCollapsed ? 'w-16' : 'w-56'}
        ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
      `}>
        {/* Logo */}
        <div className="flex items-center h-14 px-4 border-b border-slate-800">
          {!sidebarCollapsed && (
            <span className="font-semibold text-sm text-slate-200 truncate">BD Intelligence</span>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="ml-auto p-1 rounded hover:bg-slate-800 hidden lg:block"
          >
            <ChevronLeft className={`w-4 h-4 text-slate-400 transition-transform ${sidebarCollapsed ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `
                flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm
                transition-colors
                ${isActive
                  ? 'bg-blue-600/20 text-blue-400'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}
              `}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {!sidebarCollapsed && <span>{label}</span>}
            </NavLink>
          ))}

          {/* Admin-only navigation */}
          {user?.role === 'admin' && (
            <>
              <div className="mx-4 my-2 border-t border-slate-800" />
              <NavLink
                to="/admin"
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) => `
                  flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm
                  transition-colors
                  ${isActive
                    ? 'bg-purple-600/20 text-purple-400'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}
                `}
              >
                <Users className="w-5 h-5 flex-shrink-0" />
                {!sidebarCollapsed && <span>Admin</span>}
              </NavLink>
            </>
          )}
        </nav>

        {/* User section */}
        <div className="border-t border-slate-800">
          <NavLink
            to="/settings"
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) => `
              flex items-center gap-3 px-4 py-2.5 mx-2 mt-2 rounded-lg text-sm
              transition-colors
              ${isActive
                ? 'bg-blue-600/20 text-blue-400'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}
            `}
          >
            <Settings className="w-5 h-5 flex-shrink-0" />
            {!sidebarCollapsed && <span>Settings</span>}
          </NavLink>
          
          <div className="p-3">
            {!sidebarCollapsed && user && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500 truncate">{user.name || user.email}</span>
                <button onClick={logout} className="p-1 rounded hover:bg-slate-800">
                  <LogOut className="w-4 h-4 text-slate-500" />
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 h-14 px-4 border-b border-slate-800 bg-slate-900/50">
          <button onClick={() => setMobileOpen(true)} className="lg:hidden p-1">
            <Menu className="w-5 h-5 text-slate-400" />
          </button>

          {/* Global search */}
          <form onSubmit={handleAsk} className="flex-1 max-w-2xl">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                ref={searchInputRef}
                type="text"
                value={askQuery}
                onChange={(e) => setAskQuery(e.target.value)}
                placeholder="Ask anything..."
                className="w-full pl-10 pr-20 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
              <kbd className="absolute right-3 top-1/2 -translate-y-1/2 px-2 py-0.5 bg-slate-700/50 border border-slate-600 rounded text-xs text-slate-400 font-mono">
                {navigator.platform.indexOf('Mac') === 0 ? '⌘K' : 'Ctrl+K'}
              </kbd>
            </div>
          </form>

          {/* Help / Guide */}
          <NavLink to="/guide" className="relative p-2 rounded-lg hover:bg-slate-800">
            <HelpCircle className="w-5 h-5 text-slate-400" />
          </NavLink>

          {/* Notifications */}
          <NotificationDropdown />

          {/* Theme toggle */}
          <ThemeToggle />

          {/* User avatar */}
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-medium">
            {user?.name?.[0] || user?.email?.[0] || '?'}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
