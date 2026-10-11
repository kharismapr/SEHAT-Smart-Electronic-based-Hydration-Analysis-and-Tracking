import React from 'react';
import {
  Activity,
  History,
  Radio,
  Battery,
  BatteryMedium,
  BatteryLow
} from 'lucide-react';

/**
 * Sidebar Component
 * Palette: #054867 (Deep Ocean), #1081b7 (Vibrant Azure), #83c4e2 (Soft Sky), White
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
        return {
          dotColor: 'bg-[#83c4e2] shadow-[0_0_8px_#83c4e2]',
          textColor: 'text-white',
          bgColor: 'bg-[#054867]/80',
          borderColor: 'border-[#83c4e2]/40',
          label: 'Connected'
        };
      case 'Connecting':
        return {
          dotColor: 'bg-amber-400 animate-pulse shadow-[0_0_8px_rgba(251,191,36,0.8)]',
          textColor: 'text-amber-100',
          bgColor: 'bg-amber-950/60',
          borderColor: 'border-amber-700/40',
          label: 'Connecting'
        };
      case 'Disconnected':
      default:
        return {
          dotColor: 'bg-rose-400',
          textColor: 'text-rose-100',
          bgColor: 'bg-rose-950/60',
          borderColor: 'border-rose-700/40',
          label: 'Disconnected'
        };
    }
  };

  const statusInfo = getStatusDisplay(connectionStatus);

  const getBatteryIcon = (level) => {
    if (level <= 20) return <BatteryLow className="w-3.5 h-3.5 text-amber-300" />;
    if (level <= 60) return <BatteryMedium className="w-3.5 h-3.5 text-[#83c4e2]" />;
    return <Battery className="w-3.5 h-3.5 text-[#83c4e2]" />;
  };

  return (
    <aside
      className="w-full lg:w-64 text-white p-4 lg:p-6 flex flex-col justify-between shrink-0 shadow-lg border-b lg:border-b-0 lg:border-r border-[#1081b7]/40"
      style={{
        background: 'linear-gradient(180deg, #1081b7 0%, #054867 100%)'
      }}
    >
      {/* Top Header / Brand & Nav */}
      <div className="space-y-6">
        
        {/* Brand & Mobile Status Row */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <h1 className="text-2xl font-black tracking-tight text-white font-sans">
              SEHAT
            </h1>
            <p className="text-[11px] text-[#83c4e2] font-semibold tracking-wider uppercase">
              Smart Electronic-based Hydration Analysis & Tracking
            </p>
          </div>

          {/* Quick Status Badges for Mobile */}
          <div className="flex lg:hidden items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${statusInfo.bgColor} ${statusInfo.borderColor} ${statusInfo.textColor}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${statusInfo.dotColor}`} />
              {statusInfo.label}
            </span>
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono font-bold bg-white/10 border border-white/20 text-white">
              {getBatteryIcon(batteryLevel)}
              {batteryLevel}%
            </span>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="grid grid-cols-2 lg:flex lg:flex-col gap-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`flex items-center justify-center lg:justify-between px-4 py-3 rounded-2xl text-xs font-bold transition-all cursor-pointer ${
                  isActive
                    ? 'bg-white/20 text-white border border-white/30 shadow-sm backdrop-blur-md'
                    : 'text-white/80 hover:bg-white/10 hover:text-white border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-[#83c4e2]'}`} />
                  <span className="tracking-wide">{item.label}</span>
                </div>
                {item.badge !== null && (
                  <span
                    className={`ml-1.5 lg:ml-0 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                      isActive
                        ? 'bg-[#83c4e2] text-[#054867]'
                        : 'bg-white/15 text-white'
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
      <div className="hidden lg:block mt-8 pt-5 border-t border-white/15 space-y-2.5">
        <div className={`flex items-center justify-between px-4 py-2.5 rounded-xl border backdrop-blur-sm ${statusInfo.bgColor} ${statusInfo.borderColor}`}>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${statusInfo.dotColor}`} />
            <span className={`text-xs font-bold ${statusInfo.textColor}`}>
              {statusInfo.label}
            </span>
          </div>
          <Radio className={`w-3.5 h-3.5 text-[#83c4e2]`} />
        </div>

        <div className="flex items-center justify-between px-4 py-2.5 rounded-xl bg-white/10 border border-white/15 text-xs backdrop-blur-sm">
          <div className="flex items-center gap-2">
            {getBatteryIcon(batteryLevel)}
            <span className="font-semibold text-white/90">Sensor Battery</span>
          </div>
          <span className="font-mono font-bold text-white">
            {batteryLevel}%
          </span>
        </div>
      </div>

    </aside>
  );
};
