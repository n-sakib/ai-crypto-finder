import { Outlet, Link, useLocation } from 'react-router-dom';
import { BarChart3, Activity, Radio, MessageCircle, TrendingUp, Zap, Flame } from 'lucide-react';

export default function App() {
  const location = useLocation();

  const navItems = [
    { to: '/', icon: BarChart3, label: 'Dashboard' },
    { to: '/pipeline', icon: Activity, label: 'Pipeline' },
    { to: '/telegram', icon: Radio, label: 'Telegram' },
    { to: '/reddit', icon: MessageCircle, label: 'Reddit' },
    { to: '/twitter', icon: TrendingUp, label: 'Twitter' },
    { to: '/gmgn', icon: Zap, label: 'GMGN' },
    { to: '/dexscreener', icon: Flame, label: 'DexScreener' },
  ];

  return (
    <div className="h-full flex flex-col bg-[#0a0a0f] text-[#e4e4e7]">
      <header className="shrink-0 z-50 border-b border-[#1e1e2e] bg-[#0a0a0f]/85 backdrop-blur-md">
        <div className="px-2 h-12 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 no-underline">
            <div className="w-7 h-7 rounded-md flex items-center justify-center bg-gradient-to-br from-indigo-500 to-purple-500">
              <BarChart3 size={15} color="white" />
            </div>
            <span className="font-bold text-base text-[#e4e4e7]">AI Crypto Finder</span>
          </Link>

          <nav className="flex items-center gap-0.5">
            {navItems.map(({ to, icon: Icon, label }) => {
              const active = location.pathname === to || (to !== '/' && location.pathname.startsWith(to));
              return (
                <Link
                  key={to}
                  to={to}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors no-underline ${
                    active ? 'text-indigo-400 bg-indigo-500/10' : 'text-[#71717a] hover:text-[#e4e4e7]'
                  }`}
                >
                  <Icon size={14} />
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="flex-1 min-h-0 overflow-y-auto">
        <Outlet />
      </main>

      <footer className="shrink-0 border-t border-[#1e1e2e] py-2 text-center text-xs text-[#71717a]">
        AI Crypto Finder v0.1.0 — Not financial advice. Always DYOR.
      </footer>
    </div>
  );
}
