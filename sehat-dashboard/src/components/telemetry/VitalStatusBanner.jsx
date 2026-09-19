import React from 'react';
import { ShieldCheck, AlertTriangle } from 'lucide-react';
import { classifyHydration } from '../../utils/calculations';
import { HYDRATION_RULES } from '../../constants/config';

/**
 * VitalStatusBanner Component (Clean & Minimal)
 */
export const VitalStatusBanner = ({ hoursSinceHydration }) => {
  const status = classifyHydration(hoursSinceHydration);
  const isAtRisk = status.key === 'AT_RISK';

  return (
    <div
      className={`rounded-2xl border p-6 sm:p-7 transition-all shadow-sm ${
        isAtRisk
          ? 'bg-rose-50/60 border-rose-200 text-rose-950'
          : 'bg-emerald-50/60 border-emerald-200 text-emerald-950'
      }`}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
        {/* Classification Status */}
        <div className="space-y-2">
          <span
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border ${
              isAtRisk
                ? 'bg-rose-100 border-rose-300 text-rose-800'
                : 'bg-emerald-100 border-emerald-300 text-emerald-800'
            }`}
          >
            {isAtRisk ? (
              <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />
            ) : (
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            )}
            {status.label}
          </span>

          <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-900">
            {status.label}
          </h2>
        </div>

        {/* Hours Since Hydration Output */}
        <div className="bg-white border border-slate-200 px-5 py-3.5 rounded-xl shadow-xs">
          <p className="text-xs uppercase tracking-wider text-slate-400 font-bold">
            Hours Since Hydration
          </p>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-3xl sm:text-4xl font-black text-slate-900 font-mono">
              {Number(hoursSinceHydration).toFixed(1)}
            </span>
            <span className="text-sm font-bold text-slate-500">hours</span>
          </div>
        </div>
      </div>
    </div>
  );
};
