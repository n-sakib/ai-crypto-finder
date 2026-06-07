import React from 'react';
import { Radio, BarChart3 } from 'lucide-react';

interface Props {
  sourceMentions: Record<string, number>;
  totalMentions: number;
}

export default function GroupMentionsPanel({ sourceMentions, totalMentions }: Props) {
  const entries = Object.entries(sourceMentions).sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) return null;

  const maxCount = entries[0]?.[1] ?? 1;

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 mb-2">
        <Radio size={11} className="text-indigo-400" />
        <span className="text-[10px] uppercase tracking-wider text-[#52525b]">
          Group Breakdown ({entries.length} groups · {totalMentions} mentions)
        </span>
      </div>

      <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
        {entries.map(([groupName, count]) => {
          const pct = totalMentions > 0 ? Math.round((count / totalMentions) * 100) : 0;
          const barWidth = maxCount > 0 ? Math.round((count / maxCount) * 100) : 0;

          return (
            <div key={groupName} className="group">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs text-[#a1a1aa] truncate max-w-[160px]" title={groupName}>
                  {groupName.startsWith('@') ? groupName : `@${groupName}`}
                </span>
                <span className="text-xs font-mono text-[#e4e4e7] tabular-nums">
                  {count}
                  <span className="text-[10px] text-[#52525b] ml-1">({pct}%)</span>
                </span>
              </div>
              <div className="w-full bg-[#1a1a24] rounded-full h-1.5 border border-[#1e1e2e]">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${barWidth}%`,
                    backgroundColor: pct > 50
                      ? '#6366f1'
                      : pct > 25
                        ? '#818cf8'
                        : pct > 10
                          ? '#a5b4fc'
                          : '#6366f140',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
