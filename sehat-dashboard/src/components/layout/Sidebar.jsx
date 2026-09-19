import React from 'react';
import {
  Activity,
  History,
  Droplet,
  Radio,
  Battery,
  BatteryMedium,
  BatteryLow
} from 'lucide-react';

/**
 * Sidebar Component (Fully Mobile & Desktop Responsive)
 * On mobile/tablets: Compact top navigation bar + quick pills.
 * On desktops (lg+): Vertical sidebar.
 */
export const Sidebar = ({
  activeTab,
  onSelectTab,
  historyCount = 0,
  connectionStatus = 'Connected',
  batteryLevel = 84
}) => {
  const navItems = [
    { id: 'dashboard', label: 'Measurement', icon: Activity },
    { id: 'history', label: 'History', icon: History, badge: historyCount > 0 ? historyCount : null }
  ];

  const getStatusDisplay = (status) => {
    switch (status) {
      case 'Connected':
        return { dotColor: 'bg-emerald-500', textColor: 'text-emerald-700', bgColor: 'bg-emerald-50', borderColor: 'border-emerald-200', label: 'Connected' };
      case 'Connecting':
        return { dotColor: 'bg-amber-500 animate-pulse', textColor: 'text-amber-700', bgColor: 'bg-amber-50', borderColor: 'border-amber-200', label: 'Connecting' };
      case 'Disconnected':
      default:
        return { dotColor: 'bg-rose-500', textColor: 'text-rose-700', bgColor: 'bg-rose-50', borderColor: 'border-rose-200', label: 'Disconnected' };
    }
  };

  const statusInfo = getStatusDisplay(connectionStatus);

  const getBatteryIcon = (level) => {
    if (level <= 20) return <BatteryLow className="w-3.5 h-3.5 text-rose-500" />;
    if (level <= 60) return <BatteryMedium className="w-3.5 h-3.5 text-amber-500" />;
    return <Battery className="w-3.5 h-3.5 text-emerald-600" />;
  };

  return (
    <aside className="w-full lg:w-64 bg-white border-b lg:border-b-0 lg:border-r border-slate-200 p-4 lg:p-5 flex flex-col justify-between shrink-0">
      
      {/* Top Header / Brand & Nav */}
      <div className="space-y-4 lg:space-y-6">
        
        {/* Brand & Mobile Status Row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-emerald-600 flex items-center justify-center shadow-xs">
              <Droplet className="w-4 h-4 text-white fill-white" />
            </div>
            <div>
              <h1 className="text-sm font-black tracking-tight text-slate-900">
                SEHAT
              </h1>
              <p className="text-[10px] text-slate-400 font-semibold leading-none">
                Hydration Tracking
              </p>
            </div>
          </div>

          {/* Quick Status Badges for Mobile */}
          <div className="flex lg:hidden items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${statusInfo.bgColor} ${statusInfo.borderColor} ${statusInfo.textColor}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${statusInfo.dotColor}`} />
              {statusInfo.label}
            </span>
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono font-bold bg-slate-50 border border-slate-200 text-slate-700">
              {getBatteryIcon(batteryLevel)}
              {batteryLevel}%
            </span>
          </div>
        </div>

        {/* Navigation Tabs (Horizontal on mobile, Vertical on desktop) */}
        <nav className="grid grid-cols-2 lg:flex lg:flex-col gap-1.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`flex items-center justify-center lg:justify-between px-3 py-2 lg:py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                  isActive
                    ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-emerald-600' : 'text-slate-400'}`} />
                  <span>{item.label}</span>
                </div>
                {item.badge !== null && (
                  <span
                    className={`ml-1.5 lg:ml-0 px-2 py-0.2 rounded-full text-[10px] font-mono font-bold ${
                      isActive
                        ? 'bg-emerald-200/70 text-emerald-900'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Desktop-only Device Status Footer Card */}
      <div className="hidden lg:block mt-8 pt-4 border-t border-slate-100 space-y-2">
        <div className={`flex items-center justify-between px-3.5 py-2 rounded-xl border ${statusInfo.bgColor} ${statusInfo.borderColor}`}>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${statusInfo.dotColor}`} />
            <span className={`text-xs font-bold ${statusInfo.textColor}`}>
              {statusInfo.label}
            </span>
          </div>
          <Radio className={`w-3.5 h-3.5 ${statusInfo.textColor}`} />
        </div>

        <div className="flex items-center justify-between px-3.5 py-2 rounded-xl bg-slate-50 border border-slate-200 text-xs">
          <div className="flex items-center gap-2">
            {getBatteryIcon(batteryLevel)}
            <span className="font-semibold text-slate-600">Battery</span>
          </div>
          <span className="font-mono font-bold text-slate-800">
            {batteryLevel}%
          </span>
        </div>
      </div>

    </aside>
  );
};
