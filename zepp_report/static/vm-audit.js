import { $, state, escape, number } from './state.js';

export function retentionLabel(days) {
  if (!Number.isFinite(Number(days)) || Number(days) <= 0) return '保留期限未提供';
  return Number(days) % 365 === 0 ? `保留 ${Number(days) / 365} 年` : `保留 ${number(days)} 天`;
}

export function renderVmAudit(audit) {
  const configured = audit?.configured === true;
  $('vm-audit-policy').textContent = configured
    ? `${retentionLabel(audit.retention_days)} · ${audit.interval_minutes ? `自动每 ${number(audit.interval_minutes)} 分钟核对` : '核对周期未提供'}`
    : '尚未配置 VM 读回核对；归档与 HTTP 投递状态不能代表已核对。';
  const labels = {
    verified: '已读回核对', pending: '等待核对', running: '核对中',
    waiting: '等待补齐核对', conflict: '数值冲突', expired: '正常过期', failed: '核对失败',
  };
  $('vm-audit-states').innerHTML = configured ? Object.entries(labels).map(([key, label]) =>
    `<div><span>${label}</span><strong>${escape(number(audit.states?.[key] || 0))} 天</strong></div>`
  ).join('') : '';
  const checked = audit?.last_checked
    ? new Intl.DateTimeFormat('zh-CN', { timeZone: state.timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(audit.last_checked * 1000))
    : '尚未核对';
  $('vm-audit-detail').textContent = configured
    ? `最近核对：${checked} · 缺失 ${number(audit.missing_samples || 0)} 个样本 · 冲突 ${number(audit.conflict_samples || 0)} 个样本 · 累计安排补投 ${number(audit.repaired_samples || 0)} 个样本。缺失数据补投后仍需再次读回核对；核对失败后会自动重试。超出保留期属于正常过期，不计为同步失败。`
    : '';
  $('vm-audit-error').textContent = configured ? audit.error || '' : '';
}
