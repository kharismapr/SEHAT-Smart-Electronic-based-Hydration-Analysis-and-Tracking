import React from 'react';
import { Heart, Activity, Thermometer, CloudRain } from 'lucide-react';
import { SensorMetricCard } from './SensorMetricCard';

/**
 * SensorGrid Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const SensorGrid = ({ reading, isLive = false }) => {
  const { bpm = 72, gsr = 6.4, temperature = 36.6, humidity = 55 } = reading || {};

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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* PPG (Heart Rate) */}
        <SensorMetricCard
          label="Heartbeat (PPG)"
          value={bpm}
          unit="BPM"
          icon={Heart}
        />

        {/* GSR (Galvanic Skin Response) */}
        <SensorMetricCard
          label="Skin Conductance"
          value={gsr}
          unit="μS"
          icon={Activity}
        />

        {/* Body Temperature */}
        <SensorMetricCard
          label="Temperature"
          value={temperature}
          unit="°C"
          icon={Thermometer}
        />

        {/* Ambient Humidity */}
        <SensorMetricCard
          label="Humidity"
          value={humidity}
          unit="%"
          icon={CloudRain}
        />
      </div>
    </div>
  );
};
