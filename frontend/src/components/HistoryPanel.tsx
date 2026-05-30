import { useState, useEffect } from 'react';
import type { HistoryItem } from '../types';

interface HistoryPanelProps {
  compact?: boolean;
  onQuerySelect?: (query: string) => void;
  refreshKey?: number;
}

function getHistory(): HistoryItem[] {
  try {
    const stored = localStorage.getItem('query_history');
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveHistory(history: HistoryItem[]): void {
  localStorage.setItem('query_history', JSON.stringify(history.slice(0, 50)));
}

export function addToHistory(query: string, sourceCount: number): void {
  const history = getHistory();
  history.unshift({
    id: Date.now().toString(),
    query,
    timestamp: Date.now(),
    sourceCount,
  });
  saveHistory(history);
}

export function HistoryPanel({ compact = false, onQuerySelect, refreshKey }: HistoryPanelProps) {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    setHistory(getHistory());
  }, [refreshKey]);

  const filtered = history.filter(item =>
    item.query.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = (item: HistoryItem) => {
    onQuerySelect?.(item.query);
  };

  const handleClear = () => {
    localStorage.removeItem('query_history');
    setHistory([]);
  };

  const formatTime = (ts: number) => {
    const date = new Date(ts);
    return date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  if (compact) {
    return (
      <div className="history-list">
        {filtered.length === 0 ? (
          <div style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--faint)' }}>
            No history yet
          </div>
        ) : (
          filtered.slice(0, 5).map(item => (
            <div key={item.id} className="history-item" onClick={() => handleSelect(item)}>
              <span>{item.query}</span>
              <small>{formatTime(item.timestamp)}</small>
            </div>
          ))
        )}
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-medium text-gray-700">查询历史</h3>
        {history.length > 0 && (
          <button onClick={handleClear} className="text-xs text-gray-400 hover:text-red-500">
            清空
          </button>
        )}
      </div>

      <input
        type="text"
        placeholder="搜索历史..."
        value={search}
        onChange={e => setSearch(e.target.value)}
        className="w-full px-3 py-2 border rounded text-sm mb-3"
      />

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">暂无历史记录</p>
        ) : (
          filtered.map(item => (
            <button
              key={item.id}
              onClick={() => handleSelect(item)}
              className="w-full text-left p-2 rounded hover:bg-gray-50 group"
            >
              <p className="text-sm text-gray-800 truncate">{item.query}</p>
              <p className="text-xs text-gray-400">{formatTime(item.timestamp)} · {item.sourceCount} 条来源</p>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
