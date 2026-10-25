import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiOrigin } from '../../api/client';
import type { Story } from '../../api/types';

type Draft = { id: string; story_id: string; status: string; model: string; output: { title: string; bullets: { text: string; article_ids: string[] }[]; unknowns: string[] } };
type Pair = { a: string; b: string; a_title: string; b_title: string; a_publisher: string; b_publisher: string; predicted_same_event: boolean; same_event: boolean | null };
type Quality = { batch_id: string; input_hash: string; article_count: number; group_count: number; singleton_groups: number; publishers: Record<string, number>; pairs: Pair[]; notice: string };
async function request<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${apiOrigin}/api/editorial${path}`, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const value = await r.json();
  if (!r.ok) throw new Error(value.error?.message || value.detail || '편집 도구에 연결하지 못했습니다.');
  return value as T;
}
function download(value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = 'cluster-pair-review.json'; a.click(); URL.revokeObjectURL(url);
}
export function EditorialPanel({ stories: _stories }: { stories: Story[] }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [labels, setLabels] = useState<Quality | null>(null);
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const client = useQueryClient();
  const drafts = useQuery({ queryKey: ['editorial-drafts'], queryFn: () => request<{ items: Draft[] }>('/drafts'), enabled: open, retry: false });
  const candidates = useQuery({ queryKey: ['editorial-candidates'], queryFn: () => request<{ items: { id: string; title: string; article_count: number; summary_status: string }[] }>('/candidates'), enabled: open, retry: false });
  const quality = useQuery({ queryKey: ['editorial-quality'], queryFn: () => request<Quality>('/quality'), enabled: open, retry: false });
  const current = labels || quality.data;
  async function action(path: string, body: unknown) {
    setBusy(true); setError('');
    try { await request(path, body); await Promise.all([drafts.refetch(), candidates.refetch()]); await client.invalidateQueries({ queryKey: ['feed'] }); await client.invalidateQueries({ queryKey: ['story'] }); }
    catch (e) { setError(e instanceof Error ? e.message : '요청에 실패했습니다.'); }
    finally { setBusy(false); }
  }
  return <section className="editorial-panel">
    <button onClick={() => setOpen(!open)} aria-expanded={open}>요약·군집 품질 검토 {open ? '닫기' : '열기'}</button>
    {open && <>
      <h2>요약 검토와 게시</h2>
      <button disabled={busy} onClick={() => { void drafts.refetch(); void candidates.refetch(); void quality.refetch(); }}>목록 새로고침</button>
      <p>생성 시 엘리스 API를 호출합니다. 원문·출처·아래 초안을 비교한 뒤 승인하면 홈에 표시됩니다. 승인은 정치적 중립이나 사실성을 보장하지 않습니다.</p>
      <label>요약할 뉴스<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">뉴스를 선택해주세요</option>{candidates.data?.items.map(s => <option key={s.id} value={s.id}>{s.title} · 기사 {s.article_count}개{s.summary_status === 'ready' ? ' · 게시됨' : ''}</option>)}</select></label>
      <button disabled={busy || !selected} onClick={() => void action(`/stories/${encodeURIComponent(selected)}/generate`, {})}>선택 뉴스 요약 생성</button>
      {drafts.data?.items.map(d => <article className="editorial-draft" key={d.id}>
        <small>{d.status === 'approved' ? '게시됨' : d.status === 'rejected' ? '보류됨' : '초안'} · {d.model}</small><h3>{d.output.title}</h3>
        <ul>{d.output.bullets.map((b, i) => <li key={i}>{b.text}<small>관련 기사 {b.article_ids.length}개 근거</small></li>)}</ul>
        {d.output.unknowns.map((s, i) => <p key={i}>{s}</p>)}
        <a href={`/?story=${encodeURIComponent(d.story_id)}&panel=sources`} target="_blank" rel="noreferrer">기사 출처 비교</a>
        <button disabled={busy || d.status === 'approved'} onClick={() => void action(`/drafts/${d.id}/review`, { approve: true })}>승인·홈에 게시</button>
        <button disabled={busy || d.status === 'rejected'} onClick={() => void action(`/drafts/${d.id}/review`, { approve: false })}>게시 보류</button>
      </article>)}
      <h2>군집 품질 평가</h2>
      {current && <>
        <p>기사 {current.article_count}개 · 군집 {current.group_count}개 · 단독 군집 {current.singleton_groups}개</p>
        <p>{Object.entries(current.publishers).map(([name, n]) => `${name} ${n}개`).join(' / ')}</p>
        <p>{current.notice}</p>
        <p>정답 작성 {current.pairs.filter(p => p.same_event !== null).length} / {current.pairs.length}쌍</p>
        <button onClick={() => download(current)}>정답 작성 파일 다운로드</button>
        <label>작성 파일 불러오기<input type="file" accept=".json,application/json" onChange={async e => {
          try { const file = e.target.files?.[0]; if (!file) return; if (file.size > 5000000) throw new Error('5MB 이하 파일만 불러올 수 있습니다.');
            const value = JSON.parse(await file.text());
            if (value.input_hash !== quality.data?.input_hash || value.batch_id !== quality.data?.batch_id || !Array.isArray(value.pairs)) throw new Error('현재 데이터에 맞는 정답 파일을 선택해주세요.');
            const verified = await request<Record<string, unknown>>('/quality/evaluate', value); setLabels(value); setResult(verified); setPage(0); setError('');
          } catch (e) { setError(e instanceof Error ? e.message : '파일을 읽지 못했습니다.'); }
        }} /></label>
        {current.pairs.slice(page * 10, page * 10 + 10).map((p, i) => <div className="quality-pair" key={`${p.a}-${p.b}`}>
          <p>{p.a_title} <small>{p.a_publisher}</small></p><p>{p.b_title} <small>{p.b_publisher}</small></p>
          <label>같은 사건인가요?<select value={p.same_event === null ? '' : String(p.same_event)} onChange={e => {
            const pairs = [...current.pairs]; pairs[page * 10 + i] = { ...p, same_event: e.target.value === '' ? null : e.target.value === 'true' }; setLabels({ ...current, pairs }); setResult(null);
          }}><option value="">판단 대기</option><option value="true">같은 사건</option><option value="false">다른 사건</option></select></label>
        </div>)}
        <div className="editorial-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button><span>{page + 1} / {Math.max(1, Math.ceil(current.pairs.length / 10))}</span><button disabled={(page + 1) * 10 >= current.pairs.length} onClick={() => setPage(page + 1)}>다음</button></div>
        <button disabled={busy} onClick={async () => { setBusy(true); try { setResult(await request('/quality/evaluate', current)); setError(''); } catch (e) { setError(e instanceof Error ? e.message : '평가에 실패했습니다.'); } finally { setBusy(false); } }}>작성한 정답으로 평가</button>
      </>}
      {result && <div role="status"><p>검토한 {String(result.labeled_pairs)}쌍 / 전체 {String(result.total_pairs)}쌍</p>
        <p>Precision {result.precision === null ? '계산 불가' : Number(result.precision).toFixed(3)} · Recall {result.recall === null ? '계산 불가' : Number(result.recall).toFixed(3)} · F1 {result.f1 === null ? '계산 불가' : Number(result.f1).toFixed(3)}</p><p>{String(result.notice)}</p></div>}
      {busy && <p role="status">처리 중입니다…</p>}
      {(error || drafts.error || quality.error || candidates.error) && <p role="alert">{error || drafts.error?.message || quality.error?.message || candidates.error?.message}</p>}
    </>}
  </section>;
}
