import { ArrowUpRight } from 'lucide-react';
import type { ReadingMode, ReadingResult } from '../api/reading';
import { useReadingAnalysis } from '../hooks/useReadingAnalysis';

const titles: Record<ReadingMode, string> = {
  five_w: '다섯 가지 질문으로 읽기', easy: '쉽게 읽기',
  sentiment: '기사의 감정과 어조', perspectives: '같은 쟁점, 다른 입장',
};
const descriptions = {
  five_w: '기사에서 확인할 수 있는 항목부터 정리해 드려요.',
  easy: '어려운 표현을 풀어 핵심 내용을 쉽게 설명해 드려요.',
  sentiment: '기사 전체의 표현과 어조를 원문 근거와 함께 살펴봐요.',
  perspectives: '',
};
type Props = { mode: ReadingMode; storyId?: string; revision?: string; onCite?: (ids: string[]) => void; clusterPreview?: boolean };
type Cite = (ids: string[]) => void;
type Evidence = NonNullable<ReadingResult['output']>['items'][number]['evidence'];

function EvidenceFooter({ evidence, onCite }: { evidence: Evidence; onCite: Cite }) {
  const unique = [...new Map(evidence.map(e => [e.article_id + '\0' + e.quote, e])).values()];
  return <footer className="reading-card-footer" aria-label="분석 근거와 출처">
    <details className="reading-evidence">
      <summary>원문 근거</summary>
      <div className="reading-quotes">{unique.map((e, i) => <blockquote key={i}>{e.quote}</blockquote>)}</div>
    </details>
    <button className="reading-source-button" onClick={() => onCite([...new Set(unique.map(e => e.article_id))])}>
      출처 보기 <ArrowUpRight size={15} aria-hidden="true" />
    </button>
  </footer>;
}

export function ReadingResults({ data, onCite }: { data: ReadingResult; onCite: Cite }) {
  const output = data.output;
  if (!output) return null;
  const source = (id: string) => data.sources?.find(s => s.id === id);
  // The comparison API is retained for later development; it has no public UI.
  if (data.mode === 'perspectives') return null;
  if (!output.items.length) return <div className="reading-card reading-empty" role="status">
    <p>원문에서 확인할 수 있는 항목을 찾지 못했어요. 출처를 확인하거나 다시 시도해 주세요.</p>
    <button className="reading-source-button" onClick={() => onCite([])}>원문 출처 보기 <ArrowUpRight size={15} aria-hidden="true" /></button>
  </div>;
  const shared = data.mode === 'easy';
  return <div className="reading-results">
    {data.mode === 'five_w' && output.items.length < 5 && <p className="reading-partial-note" role="status">
      원문에서 확인된 {output.items.length}개 항목을 표시합니다.
    </p>}
    {output.items.map((item, i) => {
      const id = item.evidence[0]?.article_id;
      return <article className={data.mode === 'sentiment' ? 'tone-card' : 'reading-card'} key={id + '-' + i}>
        {data.mode === 'sentiment' && <header className="reading-article-header">
          <small>{String(source(id)?.publisher || '보도 출처')}</small>
          <h4>{String(source(id)?.title || '기사 전체 분석')}</h4>
        </header>}
        <h4 className={data.mode === 'sentiment' ? 'tone-label' : 'reading-item-label'}>{item.label}</h4>
        <p className="reading-item-text">{item.text}</p>
        {!shared && <EvidenceFooter evidence={item.evidence} onCite={onCite} />}
      </article>;
    })}
    {shared && <div className="reading-card reading-shared-footer">
      <EvidenceFooter evidence={output.items.flatMap(item => item.evidence)} onCite={onCite} />
    </div>}
  </div>;
}

function ConnectedAnalysisPanel({ mode, storyId, revision, onCite }: { mode: ReadingMode; storyId: string; revision?: string; onCite: Cite }) {
  const { query, generate } = useReadingAnalysis(storyId, mode, revision);
  const data = query.data;
  const error = generate.error || query.error;
  const hasResults = !!data?.output?.items.length;
  return <section className="reading-analysis" aria-busy={generate.isPending || query.isPending}>
    <header className="reading-section-header"><h3>{titles[mode]}</h3><p>{descriptions[mode]}</p></header>
    {query.isPending && <div className="reading-card reading-state" role="status"><p>분석 정보를 불러오는 중이에요…</p></div>}
    {hasResults && data && <ReadingResults data={data} onCite={onCite} />}
    {data && !hasResults && !error && <div className="reading-card reading-state">
      <p>{data.output ? '원문 근거를 확인할 수 있는 항목이 없어요. 다시 분석하거나 출처를 확인해 주세요.' : '버튼을 누르면 이 기사를 바탕으로 내용을 정리합니다.'}</p>
      <div className="reading-state-actions">
        <button className="reading-primary-button" disabled={generate.isPending} onClick={() => generate.mutate()}>
          {generate.isPending ? '분석 중…' : data.output ? '다시 분석하기' : mode === 'sentiment' ? '감정·어조 살펴보기' : '읽기 시작'}
        </button>
        {data.output && <button className="reading-source-button" onClick={() => onCite([])}>출처 보기 <ArrowUpRight size={15} aria-hidden="true" /></button>}
      </div>
    </div>}
    {error && <div className="reading-card reading-error" role="alert"><p>{error.message}</p>
      <button className="reading-primary-button" disabled={generate.isPending} onClick={() => query.error ? void query.refetch() : generate.mutate()}>다시 시도</button>
    </div>}
  </section>;
}

export function AnalysisPanel({ mode, storyId, revision, onCite = () => {} }: Props) {
  if (mode === 'perspectives') return null;
  if (!storyId?.startsWith('db-cluster-')) return <div className="reading-card reading-empty" role="status">
    <p>이 뉴스의 추가 읽기를 제공하지 않습니다.</p>
    <button className="reading-source-button" onClick={() => onCite([])}>원문 출처 보기 <ArrowUpRight size={15} aria-hidden="true" /></button>
  </div>;
  return <ConnectedAnalysisPanel mode={mode} storyId={storyId} revision={revision} onCite={onCite} />;
}
