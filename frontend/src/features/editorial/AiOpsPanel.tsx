import {useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {apiOrigin} from '../../api/client';

type Status={provider:string;model:string;rag_enabled:boolean;embedding_files_ready:boolean;embedding_ready:boolean;embedding_provider:string;embedding_model:string;storage:{ready:boolean};langchain_enabled:boolean;langgraph_installed:boolean;metrics_enabled:boolean;opik_export_enabled:boolean;ollama:{server_ready:boolean;model_ready:boolean}};
type Metrics={last_24_hours:{calls:number;errors:number;average_ms:number|null;input_tokens:number|null;output_tokens:number|null;estimated_cost_usd:number|null;cost_known_calls:number};notice:string};
type Run={workflow_id:string;id:string|null;phase:string;story_id:string};
async function request<T>(path:string,body?:unknown):Promise<T>{
  const r=await fetch(`${apiOrigin}/api/editorial/ai${path}`,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await r.json();if(!r.ok)throw new Error(value.error?.message||value.detail||'AI 도구 연결에 실패했습니다.');return value;
}

export function AiOpsPanel(){
  const [open,setOpen]=useState(false);const [story,setStory]=useState('');const [question,setQuestion]=useState('이 기사의 핵심 내용은 무엇인가요?');
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [run,setRun]=useState<Run|null>(null);const [retrieval,setRetrieval]=useState('');
  const [workId,setWorkId]=useState(()=>{try{return localStorage.getItem('prism:editorial:workflow')||'';}catch{return '';}});
  useEffect(()=>{if(run){setWorkId(run.workflow_id);try{localStorage.setItem('prism:editorial:workflow',run.workflow_id);}catch{}}},[run]);
  const status=useQuery({queryKey:['ai-readiness'],queryFn:()=>request<Status>('/status'),enabled:open,retry:false});
  const metrics=useQuery({queryKey:['ai-metrics'],queryFn:()=>request<Metrics>('/metrics'),enabled:open&&!!status.data?.storage.ready,retry:false});
  const candidates=useQuery({queryKey:['ai-candidates'],queryFn:async()=>{
    const r=await fetch(`${apiOrigin}/api/editorial/candidates`);if(!r.ok)throw new Error('뉴스 목록을 읽지 못했습니다.');return r.json() as Promise<{items:{id:string;title:string}[]}>;
  },enabled:open,retry:false});
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){setError(e instanceof Error?e.message:'요청에 실패했습니다.');}finally{setBusy(false);}}
  return <section className="editorial-panel ai-ops-panel"><button aria-expanded={open} onClick={()=>setOpen(!open)}>AI 연결·검색·운영 {open?'닫기':'열기'}</button>
    {open&&<>
      <h2>AI 연결 상태</h2>
      {status.data&&<dl className="ai-readiness">
        {Object.entries({'현재 모델':`${status.data.provider} · ${status.data.model}`,'검색 모델':`${status.data.embedding_model} · ${status.data.embedding_ready?'준비됨':'준비 필요'}`,'검색 DB':status.data.storage.ready?'준비됨':'스키마 준비 필요','벡터 검색':status.data.rag_enabled?'사용 중':'비활성','LangChain':status.data.langchain_enabled?'사용 중':'비활성','LangGraph':status.data.langgraph_installed?'설치됨':'설치 필요','Ollama':status.data.ollama.model_ready?'모델 준비됨':status.data.ollama.server_ready?'모델 선택 필요':'로컬 서버 준비 필요','운영 기록':status.data.metrics_enabled?'사용 중':'비활성','Opik 전송':status.data.opik_export_enabled?'메타데이터 전송 활성':'비활성'}).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>}
      <button onClick={()=>{void status.refetch();void metrics.refetch();}}>상태 새로고침</button>
      <h2>선택 뉴스 청크 검색</h2>
      <label>대상 뉴스<select aria-label="대상 뉴스" value={story} onChange={e=>setStory(e.target.value)}><option value="">뉴스 선택</option>{candidates.data?.items.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
      <label>검색 질문<input aria-label="검색 질문" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={2000}/></label>
      <button disabled={busy||!story||!question.trim()||!status.data?.embedding_ready||!status.data?.storage.ready} onClick={()=>void action(async()=>{
        const r=await request<{chunks:{article_id:string;characters:number}[];notice:string}>('/retrieve',{story_id:story,question});setRetrieval(`관련 청크 ${r.chunks.length}개 · 총 ${r.chunks.reduce((n,c)=>n+c.characters,0)}자. ${r.notice}`);
      })}>LLM 호출 없이 검색 점검</button>
      {retrieval&&<p role="status">{retrieval}</p>}
      <h2>생성 → 검토 → 게시</h2><p>새 작업은 모델을 호출해 초안을 생성하고 검토 단계에서 멈춥니다. 승인 전에는 게시하지 않습니다.</p>
      <label>기존 작업 ID<input aria-label="기존 작업 ID" value={workId} onChange={e=>setWorkId(e.target.value)} maxLength={36}/></label>
      <button disabled={busy||!workId.trim()} onClick={()=>void action(async()=>{setRun(await request<Run>(`/workflows/${encodeURIComponent(workId.trim())}`));})}>기존 작업 불러오기</button>
      <button disabled={busy||!story||!status.data?.langgraph_installed} onClick={()=>void action(async()=>{setRun(await request<Run>('/workflows',{story_id:story}));})}>검토 작업 시작</button>
      {run&&<div className="editorial-draft"><p>상태: {({awaiting_review:'검토 대기',published:'게시됨',rejected:'보류됨',failed:'실패'} as Record<string,string>)[run.phase]||run.phase}</p><small>작업 ID: {run.workflow_id}</small>
        <button disabled={busy} onClick={()=>void action(async()=>{setRun(await request<Run>(`/workflows/${run.workflow_id}`));})}>작업 상태 확인</button>
        {run.phase==='awaiting_review'&&<><p>요약 검토 도구에서 초안과 출처를 확인한 뒤 결정해주세요.</p><button disabled={busy} onClick={()=>void action(async()=>{setRun(await request<Run>(`/workflows/${run.workflow_id}/resume`,{approve:true}));})}>검토 승인·게시</button><button disabled={busy} onClick={()=>void action(async()=>{setRun(await request<Run>(`/workflows/${run.workflow_id}/resume`,{approve:false}));})}>게시 보류</button></>}
        {run.phase==='failed'&&<button disabled={busy} onClick={()=>void action(async()=>{setRun(await request<Run>(`/workflows/${run.workflow_id}/retry`,{}));})}>실패 단계 재시도</button>}
      </div>}
      <h2>최근 24시간 모델 호출</h2>{metrics.data&&<><p>호출 {metrics.data.last_24_hours.calls}회 · 오류 {metrics.data.last_24_hours.errors}회 · 평균 {metrics.data.last_24_hours.average_ms??'미측정'}ms</p><p>입력 {metrics.data.last_24_hours.input_tokens??'미제공'} / 출력 {metrics.data.last_24_hours.output_tokens??'미제공'} 토큰</p><p>추정 비용 {metrics.data.last_24_hours.estimated_cost_usd===null?'단가 또는 사용량 미설정':`$${metrics.data.last_24_hours.estimated_cost_usd}`} · 비용 확인 가능 {metrics.data.last_24_hours.cost_known_calls}회</p><small>{metrics.data.notice}</small></>}
      <p>파인튜닝은 학습 허용·사람 검토를 거친 정답 자료를 별도 도구로 준비합니다. 이 화면에서 학습을 실행하지 않습니다.</p>
      {busy&&<p role="status">처리 중입니다…</p>}{(error||status.error||metrics.error||candidates.error)&&<p role="alert">{error||status.error?.message||metrics.error?.message||candidates.error?.message}</p>}
    </>}
  </section>;
}
