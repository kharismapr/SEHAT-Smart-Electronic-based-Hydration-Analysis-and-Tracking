import React, { useState } from 'react';
import { Download, Trash2, Filter, ChevronLeft, ChevronRight, FileSpreadsheet } from 'lucide-react';
import { formatDateTime } from '../../utils/calculations';

/**
 * HistoryTable Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const HistoryTable = ({ history = [], onClear, onExport }) => {
  const [filter, setFilter] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 8;

  const filteredHistory = history.filter(item => {
    if (filter === 'ALL') return true;
    const isAtRisk = item.hoursSinceHydration > 10;
    return filter === 'AT_RISK' ? isAtRisk : !isAtRisk;
  });

  const totalPages = Math.ceil(filteredHistory.length / itemsPerPage) || 1;
  const paginatedData = filteredHistory.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  return (
    <div className="bg-white border border-[#83c4e2]/50 rounded-2xl p-6 shadow-xs space-y-5">
      {/* Header with actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#83c4e2]/30 pb-4">
        <div>
          <h3 className="text-base font-extrabold text-[#054867] tracking-tight flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-[#1081b7]" />
            Measurement History
          </h3>
          <p className="text-xs text-[#1081b7] font-medium">
            ({filteredHistory.length} entries)
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Status Filter */}
          <div className="flex items-center bg-[#f0f7fb] p-1 rounded-xl border border-[#83c4e2] text-xs">
            <Filter className="w-3.5 h-3.5 text-[#1081b7] ml-2 mr-1" />
            <select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setCurrentPage(1);
              }}
              aria-label="Filter records by hydration status"
              className="bg-transparent text-[#054867] font-medium py-1 pr-2 outline-none cursor-pointer text-xs"
            >
              <option value="ALL">All History</option>
              <option value="WELL_HYDRATED">Well Hydrated</option>
              <option value="AT_RISK">In Risk</option>
            </select>
          </div>

          {/* Export to CSV */}
          <button
            onClick={onExport}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-[#f0f7fb] hover:bg-[#e2f1f8] border border-[#83c4e2] text-[#054867] transition-colors cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-[#1081b7]" />
            Export CSV
          </button>

          {/* Clear History */}
          <button
            onClick={onClear}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-stone-50 hover:bg-stone-100 border border-stone-200 text-stone-600 transition-colors cursor-pointer"
          >
            <Trash2 className="w-3.5 h-3.5 text-stone-400" />
            Clear
          </button>
        </div>
      </div>

      {/* Table Data */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-[#054867]">
          <thead className="bg-[#f0f7fb] text-[#054867] uppercase tracking-wider text-[11px] font-bold border-b border-[#83c4e2]">
            <tr>
              <th className="py-3 px-4">Timestamp</th>
              <th className="py-3 px-4">PPG (BPM)</th>
              <th className="py-3 px-4">GSR (μS)</th>
              <th className="py-3 px-4">Temp (°C)</th>
              <th className="py-3 px-4">Humidity</th>
              <th className="py-3 px-4">Pred. Dry (h)</th>
              <th className="py-3 px-4">Classification</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#83c4e2]/20 font-mono">
            {paginatedData.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-[#054867]/50 font-sans">
                  No specimen records match the current filter.
                </td>
              </tr>
            ) : (
              paginatedData.map((row) => {
                const isAtRisk = row.hoursSinceHydration > 10;
                return (
                  <tr key={row.id} className="hover:bg-[#f0f7fb]/60 transition-colors">
                    <td className="py-3 px-4 text-[#054867]/80 font-sans font-medium">
                      {formatDateTime(row.timestamp)}
                    </td>
                    <td className="py-3 px-4 text-[#054867] font-bold">{row.bpm}</td>
                    <td className="py-3 px-4 text-[#1081b7] font-bold">{row.gsr}</td>
                    <td className="py-3 px-4 text-[#054867] font-medium">{row.temperature}°C</td>
                    <td className="py-3 px-4 text-[#054867] font-medium">{row.humidity}%</td>
                    <td className="py-3 px-4 font-black text-[#054867]">
                      {Number(row.hoursSinceHydration).toFixed(1)}h
                    </td>
                    <td className="py-3 px-4 font-sans">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase ${
                          isAtRisk
                            ? 'bg-amber-50 text-amber-900 border border-amber-300'
                            : 'bg-[#f0f7fb] text-[#054867] border border-[#83c4e2]'
                        }`}
                      >
                        {isAtRisk ? 'In Risk of Dehydration' : 'Well Hydrated'}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2 border-t border-[#83c4e2]/30 text-xs text-[#054867]/70 font-medium">
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              aria-label="Previous Page"
              className="p-1.5 rounded-lg bg-[#f0f7fb] hover:bg-[#e2f1f8] border border-[#83c4e2] disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer text-[#054867]"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              aria-label="Next Page"
              className="p-1.5 rounded-lg bg-[#f0f7fb] hover:bg-[#e2f1f8] border border-[#83c4e2] disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer text-[#054867]"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
