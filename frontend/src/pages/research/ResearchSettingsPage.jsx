import { useState } from 'react';
const DEFAULT = { provider: 'openai-compatible', baseURL: '', apiKey: '', model: '' };
export default function ResearchSettingsPage() {
  const [config, setConfig] = useState(() => { try { return { ...DEFAULT, ...JSON.parse(localStorage.getItem('airobot-research-ai') || '{}') }; } catch { return DEFAULT; } });
  const [message, setMessage] = useState(''); const [testing, setTesting] = useState(false);
  const update = (key, value) => setConfig(prev => ({ ...prev, [key]: value }));
  const save = () => { localStorage.setItem('airobot-research-ai', JSON.stringify(config)); setMessage('配置已保存到当前浏览器，不写入服务器'); };
  const test = async () => {
    setTesting(true); setMessage('正在测试…');
    try {
      // 聊天接口是流式响应，不能走只解析 JSON 的 apiFetch。
      const resp = await fetch('/api/research-workspace/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [{ role: 'user', content: '请只回复：连接正常' }], context: '这是研究工作区连接测试。', llm: config }),
      });
      const text = await resp.text();
      if (!resp.ok) throw new Error(text || `HTTP ${resp.status}`);
      setMessage(text.includes('error') ? '连接返回错误，请检查配置' : '连接正常，已收到流式响应');
    } catch (e) { setMessage(e.message || '连接失败'); } finally { setTesting(false); }
  };
  return <div className="max-w-2xl space-y-3 fade-in"><div><div className="text-xs" style={{ color: 'var(--text-muted)' }}>研究工作区</div><h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>AI 接入</h2><div className="text-xs" style={{ color: 'var(--text-muted)' }}>配置只保存在浏览器本地；没有配置时不影响行情、因子和复盘功能</div></div><section className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><div className="space-y-2 text-xs"><Field label="Provider"><input value={config.provider} onChange={e => update('provider', e.target.value)} /></Field><Field label="Base URL"><input value={config.baseURL} onChange={e => update('baseURL', e.target.value)} placeholder="https://.../v1" /></Field><Field label="API Key"><input type="password" value={config.apiKey} onChange={e => update('apiKey', e.target.value)} placeholder="只保存在本地浏览器" /></Field><Field label="Model"><input value={config.model} onChange={e => update('model', e.target.value)} placeholder="模型名称" /></Field></div><div className="mt-3 flex gap-2"><button onClick={save} className="rounded px-3 py-1.5 text-xs" style={{ background: 'var(--accent-blue)', color: '#fff' }}>保存配置</button><button onClick={test} disabled={testing} className="rounded border px-3 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>{testing ? '测试中…' : '测试连接'}</button></div>{message && <div className="mt-2 rounded px-2 py-1.5 text-xs" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>{message}</div>}</section><div className="rounded border px-3 py-2 text-[10px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>安全说明：9000 只在你点击测试/对话时转发请求，不保存 API Key。不要把真实密钥粘贴到聊天或提交到代码仓库。</div></div>;
}
function Field({ label, children }) { return <label className="grid grid-cols-[90px_1fr] items-center gap-2"><span style={{ color: 'var(--text-muted)' }}>{label}</span>{children.type === 'input' ? <div className="[&>input]:w-full [&>input]:rounded [&>input]:border [&>input]:px-2 [&>input]:py-1.5 [&>input]:text-xs [&>input]:outline-none" style={{ color: 'var(--text-primary)' }}>{children}</div> : children}</label>; }
