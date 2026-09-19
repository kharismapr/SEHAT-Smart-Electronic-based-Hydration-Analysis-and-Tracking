import React from 'react';

/**
 * SensorMetricCard Component
 * Minimalist, high-clarity metric presentation without visual clutter.
 */
export const SensorMetricCard = ({
  label,
  value,
  unit,
  icon: Icon,
  colorScheme = 'cyan'
}) => {
  const colorMap = {
    rose: {
      border: 'border-rose-200',
      iconBg: 'bg-rose-50 text-rose-600',
    },
    cyan: {
      border: 'border-cyan-200',
      iconBg: 'bg-cyan-50 text-cyan-600',
    },
    amber: {
      border: 'border-amber-200',
      iconBg: 'bg-amber-50 text-amber-600',
    },
    emerald: {
      border: 'border-emerald-200',
      iconBg: 'bg-emerald-50 text-emerald-600',
    }
  };

  const scheme = colorMap[colorScheme] || colorMap.cyan;

  return (
    <div className={`bg-white border ${scheme.border} rounded-2xl p-5 shadow-sm transition-all`}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
          {label}
        </p>
        {Icon && (
          <div className={`p-2 rounded-xl border border-slate-100 ${scheme.iconBg}`}>
            <Icon className="w-4 h-4" />
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-3xl font-black font-mono tracking-tight text-slate-900">
          {value !== undefined && value !== null ? value : '--'}
        </span>
        {unit && (
          <span className="text-xs font-bold text-slate-400 uppercase">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
};
