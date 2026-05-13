import { useState, useEffect } from 'react';

interface StatsData {
  totalArticles: number;
  totalChunks: number;
  sources: string[];
  categories: string[];
  lastUpdated: string | null;
}

export function Dashboard() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 30000); // 30秒刷新
    return () => clearInterval(interval);
  }, []);

  const fetchStats = async () => {
    try {
      const resp = await fetch('/api/stats');
      if (!resp.ok) throw new Error('Failed to fetch');
      const data = await resp.json();
      // 适配 API 返回格式
      setStats({
        totalArticles: data.total_articles || 0,
        totalChunks: data.total_chunks || data.total_articles || 0,
        sources: data.sources ? Object.keys(data.sources) : [],
        categories: data.categories ? Object.keys(data.categories) : [],
        lastUpdated: data.last_updated || null,
      });
      setError(null);
    } catch (e) {
      setError('无法加载统计');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="p-4 text-sm text-gray-500">加载中...</div>;
  if (error) return <div className="p-4 text-sm text-red-500">{error}</div>;
  if (!stats) return null;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="font-medium text-gray-700 mb-4">数据概览</h3>

      <div className="grid grid-cols-2 gap-4">
        <div className="p-3 bg-blue-50 rounded">
          <p className="text-2xl font-bold text-blue-600">{stats.totalArticles.toLocaleString()}</p>
          <p className="text-xs text-gray-500">文章总数</p>
        </div>
        <div className="p-3 bg-green-50 rounded">
          <p className="text-2xl font-bold text-green-600">{stats.totalChunks.toLocaleString()}</p>
          <p className="text-xs text-gray-500">Chunks 总数</p>
        </div>
      </div>

      <div className="mt-4">
        <p className="text-xs text-gray-500 mb-1">数据来源</p>
        <div className="flex flex-wrap gap-1">
          {stats.sources?.map(s => (
            <span key={s} className="px-2 py-0.5 bg-gray-100 rounded text-xs">{s}</span>
          ))}
        </div>
      </div>

      <div className="mt-3">
        <p className="text-xs text-gray-500 mb-1">分类分布</p>
        <div className="flex flex-wrap gap-1">
          {stats.categories?.map(c => (
            <span key={c} className="px-2 py-0.5 bg-gray-100 rounded text-xs">{c}</span>
          ))}
        </div>
      </div>

      {stats.lastUpdated && (
        <p className="text-xs text-gray-400 mt-3">
          最后更新: {new Date(stats.lastUpdated).toLocaleString('zh-CN')}
        </p>
      )}
    </div>
  );
}