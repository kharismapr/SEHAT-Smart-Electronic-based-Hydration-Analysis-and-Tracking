import React from 'react';

/**
 * SensorMetricCard Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const SensorMetricCard = ({
  label,
  value,
  unit,
  icon: Icon
}) => {
  return (
    <div className="bg-white border border-[#83c4e2]/50 hover:border-[#1081b7] rounded-2xl p-5 shadow-xs transition-all">
      <div className="flex items-center justify-between">
        <p className="text-xs font-bold uppercase tracking-wider text-[#054867]/60">
          {label}
        </p>
        {Icon && (
          <div className="p-2 rounded-xl bg-[#f0f7fb] border border-[#83c4e2]/60 text-[#1081b7]">
            <Icon className="w-4 h-4" />
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-3xl font-black font-mono tracking-tight text-[#054867]">
          {value !== undefined && value !== null ? value : '--'}
        </span>
        {unit && (
          <span className="text-xs font-bold text-[#1081b7] uppercase">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
};
