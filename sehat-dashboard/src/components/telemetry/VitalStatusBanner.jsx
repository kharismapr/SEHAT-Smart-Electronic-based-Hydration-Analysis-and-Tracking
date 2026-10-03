import React from 'react';
import { ShieldCheck, AlertCircle, Cpu, Loader2 } from 'lucide-react';
import { classifyHydration } from '../../utils/calculations';

/**
 * VitalStatusBanner Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const VitalStatusBanner = ({
  hoursSinceHydration,
  isMeasuring,
  isInferring
}) => {
  if (isMeasuring) {
    return (
      <div className="rounded-2xl border border-[#83c4e2] bg-white p-6 sm:p-7 transition-all shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
          <div className="space-y-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide bg-[#f0f7fb] border border-[#83c4e2] text-[#054867]">
              {isInferring ? (
                <>
                  <Cpu className="w-3.5 h-3.5 text-[#1081b7] animate-pulse" />
                  Running ML Inference
                </>
              ) : (
                <>
                  <Loader2 className="w-3.5 h-3.5 text-[#1081b7] animate-spin" />
                  Sampling Live Biosignals
                </>
              )}
            </span>

            <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-[#054867]">
              {isInferring
                ? 'Processing Random Forest Model...'
                : 'Acquiring Stabilized Telemetry...'}
            </h2>
            <p className="text-xs text-[#054867]/70 font-medium">
              {isInferring
                ? 'Computing multi-variable regression matrix against baseline features.'
                : 'Raw PPG, GSR, and environmental metrics are streaming below.'}
            </p>
          </div>

          <div className="bg-[#f0f7fb] border border-[#83c4e2]/60 px-6 py-4 rounded-xl shadow-xs min-w-[170px] text-center">
            <p className="text-[11px] uppercase tracking-wider text-[#054867]/70 font-bold">
              Predicted Interval Dry
            </p>
            <div className="flex items-center justify-center gap-1.5 mt-0.5">
              <span className="text-3xl sm:text-4xl font-black text-[#054867] font-mono animate-pulse">
                --
              </span>
              <span className="text-xs font-bold text-[#1081b7]">hours</span>
            </div>
            <p className="text-[10px] text-[#1081b7] font-semibold mt-1">
              Calculating...
            </p>
          </div>
        </div>
      </div>
    );
  }

  const status = classifyHydration(hoursSinceHydration);
  const isAtRisk = status.key === 'AT_RISK';

  return (
    <div
      className={`rounded-2xl border p-6 sm:p-7 transition-all shadow-xs ${
        isAtRisk
          ? 'bg-white border-amber-300 text-[#054867]'
          : 'bg-white border-[#83c4e2] text-[#054867]'
      }`}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
        {/* Classification Status */}
        <div className="space-y-2">
          <span
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border ${
              isAtRisk
                ? 'bg-amber-50 border-amber-300 text-amber-900'
                : 'bg-[#f0f7fb] border-[#83c4e2] text-[#054867]'
            }`}
          >
            {isAtRisk ? (
              <AlertCircle className="w-3.5 h-3.5 text-amber-600" />
            ) : (
              <ShieldCheck className="w-3.5 h-3.5 text-[#1081b7]" />
            )}
            {status.label}
          </span>

          <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-[#054867]">
            {status.label}
          </h2>
          <p className="text-xs text-[#054867]/70 font-medium">
            {isAtRisk
              ? 'Elevated interval without fluid intake detected by biosignal regression.'
              : 'Hydration balance is in optimal physiological equilibrium.'}
          </p>
        </div>

        {/* Predicted Hours Output */}
        <div className="bg-[#f0f7fb] border border-[#83c4e2]/60 px-5 py-3.5 rounded-xl shadow-xs min-w-[170px]">
          <p className="text-[11px] uppercase tracking-wider text-[#054867]/70 font-bold">
            Predicted Interval Dry
          </p>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-3xl sm:text-4xl font-black text-[#054867] font-mono">
              {hoursSinceHydration !== null && hoursSinceHydration !== undefined
                ? Number(hoursSinceHydration).toFixed(1)
                : '--'}
            </span>
            <span className="text-xs font-bold text-[#1081b7]">hours</span>
          </div>
        </div>
      </div>
    </div>
  );
};
