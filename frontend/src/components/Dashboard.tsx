import { useState, useEffect } from 'react';
import { getStats } from '../api/client';

interface StatsData {
  totalArticles: number;
  totalChunks: number;
  sources: string[];
  categories: string[];
  lastUpdated: string | null;
}

interface DashboardProps {
  compact?: boolean;
}

export function Dashboard({ compact = false }: DashboardProps) {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchStats = async () => {
    try {
      const data = await getStats();
      setStats({
        totalArticles: data.total_articles || 0,
        totalChunks: data.total_chunks || data.total_articles || 0,
        sources: data.sources ? Object.keys(data.sources) : [],
        categories: data.categories ? Object.keys(data.categories) : [],
        lastUpdated: data.last_updated || null,
      });
      setError(null);
    } catch (e) {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--faint)' }}>
        加载中...
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--faint)' }}>
        {error || '无数据'}
      </div>
    );
  }

  if (compact) {
    return (
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{stats.totalArticles.toLocaleString()}</div>
          <div className="stat-label">文章</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.totalChunks.toLocaleString()}</div>
          <div className="stat-label">Chunks</div>
        </div>
      </div>
    );
  }

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
    </div>
  );
}
