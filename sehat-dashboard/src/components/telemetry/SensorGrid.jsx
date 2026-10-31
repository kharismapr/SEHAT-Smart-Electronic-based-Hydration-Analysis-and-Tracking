import React from 'react';
import { Heart, Activity } from 'lucide-react';
import { SensorMetricCard } from './SensorMetricCard';

/**
 * SensorGrid Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const SensorGrid = ({ reading, isLive = false }) => {
  const { bpm = 72, spo2 = null, spo2Valid = false, gsr = 6.4 } = reading || {};

  return (
    <div className="space-y-2">
      {isLive && (
        <div className="flex items-center gap-2 text-[11px] font-bold text-[#1081b7]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#83c4e2] opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#1081b7]"></span>
          </span>
          Live Biosignal Stream (Active Sampling)
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* PPG (Heart Rate) */}
        <SensorMetricCard
          label="Heartbeat (PPG)"
          value={bpm}
          unit="BPM"
          icon={Heart}
        />

        {/* Blood oxygen saturation from MAX30102 red/IR channels */}
        <SensorMetricCard
          label="Oxygen Saturation (SpO₂)"
          value={spo2Valid ? spo2 : '—'}
          unit="%"
          icon={Activity}
        />

        {/* GSR (Galvanic Skin Response) */}
        <SensorMetricCard
          label="Skin Conductance"
          value={gsr}
          unit="μS"
          icon={Activity}
        />
      </div>
    </div>
  );
};
