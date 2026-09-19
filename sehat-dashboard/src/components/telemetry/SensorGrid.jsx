import React from 'react';
import { Heart, Activity, Thermometer, CloudRain } from 'lucide-react';
import { SensorMetricCard } from './SensorMetricCard';

/**
 * SensorGrid Component
 * Displays the 4 primary raw sensor data streams cleanly.
 */
export const SensorGrid = ({ reading }) => {
  const { bpm = 72, gsr = 6.4, temperature = 36.6, humidity = 55 } = reading || {};

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* PPG (Heart Rate) */}
      <SensorMetricCard
        label="Heartbeat (PPG)"
        value={bpm}
        unit="BPM"
        icon={Heart}
        colorScheme="rose"
      />

      {/* GSR (Galvanic Skin Response) */}
      <SensorMetricCard
        label="GSR Conductance"
        value={gsr}
        unit="μS"
        icon={Activity}
        colorScheme="cyan"
      />

      {/* Body Temperature */}
      <SensorMetricCard
        label="Temperature"
        value={temperature}
        unit="°C"
        icon={Thermometer}
        colorScheme="amber"
      />

      {/* Ambient Humidity */}
      <SensorMetricCard
        label="Humidity"
        value={humidity}
        unit="%"
        icon={CloudRain}
        colorScheme="emerald"
      />
    </div>
  );
};
