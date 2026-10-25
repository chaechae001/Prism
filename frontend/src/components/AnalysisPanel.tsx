import type {ReadingMode as AnalysisMode} from '../api/reading';
import {useReadingAnalysis} from '../hooks/useReadingAnalysis';

const titles:Record<AnalysisMode,string>={five_w:'확인된 내용을 다섯 가지 질문으로',easy:'어려운 뉴스도 쉽게 읽어요',sentiment:'기사의 표현은 어떤 어조일까요?',perspectives:'기사별로 어떤 점을 강조하나요?'};
function ConnectedAnalysisPanel({mode,storyId,onCite}:{mode:AnalysisMode;storyId:string;onCite:(ids:string[])=>void}){
 const {query,generate}=useReadingAnalysis(storyId,mode);
 const data=query.data;const error=generate.error||query.error;
 return <section className="reading-analysis" aria-busy={generate.isPending||query.isPending}>
  <span className="overline">MORE WAYS TO READ</span><h3>{titles[mode]}</h3>
  {mode==='perspectives'&&<p className="muted small">기사의 강조점을 비교합니다. 기사가 하나라면 해당 기사의 강조점만 표시하며, 언론사의 정치 성향을 판정하지 않습니다.</p>}
  {query.isPending&&<p role="status">저장된 분석을 확인하고 있습니다.</p>}
  {mode==='perspectives'&&data&&<>
    <p className="notice">{data.comparison_kind==='same_publisher'?'같은 매체의 서로 다른 기사끼리 비교합니다.':data.comparison_kind==='cross_publisher'?'여러 매체의 기사에서 공통 내용과 강조점 차이를 살펴봅니다.':data.comparison_kind==='duplicate_bodies'?'기사 링크는 여러 개지만 본문이 중복되어 독립적인 비교 자료가 부족합니다.':'현재 출처는 1개입니다. 기사가 하나여서 강조점만 확인할 수 있습니다.'}</p>
    <div className="comparison-sources" aria-label="비교 대상 기사">{data.sources?.map((source,i)=><button key={String(source.id)} onClick={()=>onCite([String(source.id)])}><small>기사 {i+1} · {String(source.publisher)}</small><strong>{String(source.title)}</strong></button>)}</div>
  </>}
  {data?.output?<>
   {mode==='perspectives'&&<>
    {data.output.comparison&&<>
     {data.output.comparison.relation==='different_events'?<p role="status" className="notice">기사들이 서로 다른 사건을 다루고 있어 직접 비교를 보류했습니다. 아래 원문을 확인해주세요.</p>:data.output.comparison.relation==='insufficient_context'?<p className="muted">비교 근거가 부족해 공통점과 차이점을 만들지 않았습니다.</p>:<>
      <h3>공통으로 확인되는 내용</h3>
      {data.output.comparison.common_ground.length?data.output.comparison.common_ground.map((item,i)=><div className="perspective" key={`common-${i}`}><h4>{item.label}</h4><p>{item.text}</p><button className="citation-button" onClick={()=>onCite([...new Set(item.evidence.map(e=>e.article_id))])}>두 기사 이상의 근거 확인 ↗</button></div>):<p className="muted">공통으로 확인할 수 있는 사실이 충분하지 않습니다.</p>}
      <h3>같은 쟁점에서 달라지는 강조점</h3>
      {data.output.comparison.differences.length?data.output.comparison.differences.map((item,i)=><div className="perspective" key={`diff-${i}`}><h4>{item.label}</h4><p>{item.text}</p>{item.evidence.map((e,j)=><blockquote key={j}><small>{String(data.sources?.find(a=>a.id===e.article_id)?.publisher||'근거 기사')}</small><br/>{e.quote}</blockquote>)}<button className="citation-button" onClick={()=>onCite([...new Set(item.evidence.map(e=>e.article_id))])}>비교 근거 확인 ↗</button></div>):<p className="muted">근거로 확인되는 차이가 없습니다. 차이를 임의로 만들지 않습니다.</p>}
     </>}
    </>}
    <h3>기사별 강조점과 근거</h3>
   </>}
   {data.output.items.map((item,i)=><article className="perspective" key={`${item.label}-${i}`}><h3>{item.label}</h3><p>{item.text}</p>
    {item.evidence.map((e,j)=><blockquote key={`${e.article_id}-${j}`}>{e.quote}</blockquote>)}
    <button className="citation-button" onClick={()=>onCite([...new Set(item.evidence.map(e=>e.article_id))])}>근거 기사 보기 ↗</button></article>)}
   {data.output.limitations.length>0&&<div className="unknowns"><strong>함께 확인할 내용</strong>{data.output.limitations.map(t=><p key={t}>{t}</p>)}</div>}
   <p className="muted small">{data.notice}</p>
  </>:data&&<div className="analysis-state"><p>이 뉴스의 본문을 근거로 분석할 수 있습니다. 버튼을 누르면 AI가 분석하며 잠시 시간이 걸립니다.</p><button className="button" disabled={generate.isPending} onClick={()=>generate.mutate()}>{generate.isPending?'분석 중…':mode==='perspectives'?((data.article_count??1)>1?'AI 비교 분석하기':'기사 강조점 분석하기'):'AI 분석하기'}</button></div>}
  {error&&<div role="alert"><p>{error.message}</p><button className="button" disabled={generate.isPending} onClick={()=>query.error?void query.refetch():generate.mutate()}>다시 시도</button></div>}
 </section>;
}


export function AnalysisPanel({mode,storyId,onCite=()=>{},clusterPreview=false}:{mode:AnalysisMode;storyId?:string;onCite?:(ids:string[])=>void;clusterPreview?:boolean}){
 // 오프라인 예제는 기존 안내를 유지하고 DB 뉴스만 서버 분석에 연결합니다.
 if(!storyId?.startsWith('db-cluster-'))return <div className="analysis-state" role="status"><h3>{titles[mode]}</h3><p>{clusterPreview?'추가 분석 결과를 준비하고 있습니다. 출처 탭에서 원문을 확인해주세요.':'분석 결과를 준비하고 있습니다. 지금은 뉴스 DM에서 요약이나 쉬운 설명을 요청할 수 있어요.'}</p></div>;
 return <ConnectedAnalysisPanel mode={mode} storyId={storyId} onCite={onCite}/>;
}
