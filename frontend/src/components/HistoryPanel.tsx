import { useState, useEffect } from 'react';

export interface HistoryItem {
  id: string;
  query: string;
  timestamp: number;
  sourceCount: number;
}

// 从 localStorage 读取历史
function getHistory(): HistoryItem[] {
  try {
    const stored = localStorage.getItem('query_history');
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveHistory(history: HistoryItem[]): void {
  localStorage.setItem('query_history', JSON.stringify(history.slice(0, 50))); // 最多50条
}

export function HistoryPanel() {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    setHistory(getHistory());
  }, []);

  const filtered = history.filter(item =>
    item.query.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = (item: HistoryItem) => {
    // 通过自定义事件通知 ChatWindow
    window.dispatchEvent(new CustomEvent('load-query', { detail: item.query }));
  };

  const handleClear = () => {
    localStorage.removeItem('query_history');
    setHistory([]);
  };

  const formatTime = (ts: number) => {
    const date = new Date(ts);
    return date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

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

// 导出保存历史的方法
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