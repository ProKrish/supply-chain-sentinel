import { NavLink, useLocation } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';

export default function AppHeader() {
  const { user, logout } = useAuth0();
  const { pathname } = useLocation();

  // Safely get user properties
  const email = user?.email || '';
  const roles = user?.["https://supply-chain-sentinel/roles"] || [];
  const primaryRole = roles[0];

  // Determine badge styling based on role
  let badgeColor = 'bg-slate-800 text-slate-300 border-[#334155]'; // viewer / none
  let badgeText = 'Viewer';
  let badgeAriaLabel = 'User role: Viewer';

  if (primaryRole === 'logistics_manager') {
    badgeColor = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-green-400 border-green-500/30';
    badgeText = 'Manager';
    badgeAriaLabel = 'User role: Logistics Manager';
  } else if (primaryRole === 'read_only_analyst') {
    badgeColor = 'bg-blue-500/10 text-blue-400 border-blue-500/30';
    badgeText = 'Analyst';
    badgeAriaLabel = 'User role: Read-only Analyst';
  }

  return (
    <header role="banner" className="fixed top-0 left-0 w-full h-16 z-50 bg-gradient-to-b from-[#1e293b] to-[#151d2b] border-b border-[#334155] flex items-center justify-between px-6">
      
      {/* LEFT SIDE */}
      <div className="flex items-center gap-3">
        {/* Custom Cyan Network SVG Icon */}
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <title>Supply Chain Sentinel Logo</title>
          <circle cx="18" cy="5" r="3" />
          <circle cx="6" cy="12" r="3" />
          <circle cx="18" cy="19" r="3" />
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
          <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
        </svg>
        <div className="flex flex-col">
          <span className="text-white font-semibold leading-tight">Supply Chain Sentinel</span>
          <span className="text-slate-300 text-xs leading-tight">Live Risk Monitor</span>
        </div>
      </div>

      {/* CENTER */}
      <nav aria-label="Main navigation" className="flex items-center h-full gap-8">
        <NavLink 
          to="/dashboard"
          aria-current={pathname === '/dashboard' ? 'page' : undefined}
          className={({ isActive }) => 
            `h-full flex items-center border-b-[2px] font-medium transition-colors ${
              isActive 
                ? 'border-[#06b6d4] text-[#06b6d4]' 
                : 'border-transparent text-slate-300 hover:text-white'
            }`
          }
        >
          Dashboard
        </NavLink>
        <NavLink 
          to="/analytics"
          aria-current={pathname === '/analytics' ? 'page' : undefined}
          className={({ isActive }) => 
            `h-full flex items-center border-b-[2px] font-medium transition-colors ${
              isActive 
                ? 'border-[#06b6d4] text-[#06b6d4]' 
                : 'border-transparent text-slate-300 hover:text-white'
            }`
          }
        >
          Analytics
        </NavLink>
      </nav>

      {/* RIGHT SIDE */}
      <div className="flex items-center gap-4">
        {user && (
          <div className="flex items-center gap-3">
            <span className="text-white text-sm">{email}</span>
            <span aria-label={badgeAriaLabel} className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${badgeColor}`}>
              {badgeText}
            </span>
          </div>
        )}
        <button 
          onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })}
          className="text-sm font-medium text-slate-300 border border-[#334155] rounded-md px-3 py-1.5 hover:bg-slate-700 hover:text-white transition-colors focus:outline focus:outline-2 focus:outline-cyan-400"
        >
          Logout
        </button>
      </div>
      
    </header>
  );
}
