import { useState, useEffect, useMemo } from 'react';
import { useDatePicker } from './useDatePicker';
import { STAGES, STAGE_COLORS } from '../constants/stages';
import { apiFetch } from '../utils/request';

const PAGE_SIZE = 20;

/**
 * Lifecycle 系列 Page 共享的数据获取+过滤+分页逻辑
 * @param {string} apiEndpoint - 如 '/api/lifecycle', '/api/lifecycle-v2', '/api/lifecycle-v3'
 * @param {object} [options] - { sortByDefault: 'strength' }
 */
export function useLifecycleData(apiEndpoint, options = {}) {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stageFilter, setStageFilter] = useState('全部');
  const [sectorFilter, setSectorFilter] = useState('全部');
  const [searchText, setSearchText] = useState('');
  const [sortBy, setSortBy] = useState(options.sortByDefault || 'strength');
  const [currentPage, setCurrentPage] = useState(0);

  // 数据加载
  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    (async () => {
      const { ok, data: d, error: err } = await apiFetch(
        `${apiEndpoint}?date=${selectedDate}`,
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      if (!ok) {
        if (/abort/i.test(err || '')) return;
        setError('数据加载失败');
        setLoading(false);
        return;
      }
      setData(d);
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, apiEndpoint]);

  // 筛选变化重置页码
  useEffect(() => { setCurrentPage(0); }, [stageFilter, sectorFilter, searchText, sortBy]);

  // 各阶段数量统计
  const stageCounts = useMemo(() => {
    if (!data?.leaders) return [];
    return STAGES.map(s => ({
      stage: s,
      count: data.leaders.filter(l => l.stage === s).length,
      color: STAGE_COLORS[s],
    }));
  }, [data]);

  // 板块列表（用于筛选下拉）
  const sectorList = useMemo(() => {
    if (!data?.leaders) return [];
    const counts = {};
    data.leaders.forEach(l => { counts[l.sector] = (counts[l.sector] || 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [data]);

  // 过滤 + 排序
  const filteredLeaders = useMemo(() => {
    if (!data?.leaders) return [];
    let result = data.leaders;
    if (stageFilter !== '全部') result = result.filter(l => l.stage === stageFilter);
    if (sectorFilter !== '全部') result = result.filter(l => l.sector === sectorFilter);
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      result = result.filter(l =>
        l.ts_code?.toLowerCase().includes(q) ||
        l.name?.toLowerCase().includes(q) ||
        l.sector?.toLowerCase().includes(q)
      );
    }
    const sorted = [...result];
    if (sortBy === 'strength') sorted.sort((a, b) => (b.strength || 0) - (a.strength || 0));
    else if (sortBy === 'days') sorted.sort((a, b) => (b.consecutive_days || 0) - (a.consecutive_days || 0));
    else if (sortBy === 'change') sorted.sort((a, b) => Math.abs(b.change_rate || 0) - Math.abs(a.change_rate || 0));
    return sorted;
  }, [data, stageFilter, sectorFilter, searchText, sortBy]);

  const totalPages = Math.ceil(filteredLeaders.length / PAGE_SIZE);
  const pagedLeaders = filteredLeaders.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const retry = () => { setError(null); setSelectedDate(selectedDate); };

  return {
    data, loading, error, retry,
    selectedDate, setSelectedDate, changeDate,
    stageFilter, setStageFilter,
    sectorFilter, setSectorFilter,
    sectorList,
    searchText, setSearchText,
    sortBy, setSortBy,
    stageCounts,
    filteredLeaders, pagedLeaders,
    currentPage, setCurrentPage, totalPages,
  };
}
