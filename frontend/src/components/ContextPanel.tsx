import {useEffect,useRef,useState} from 'react';
import {useMutation} from '@tanstack/react-query';
import {publicContext,imageEvidence,type Indicator} from '../api/evidence';

export function ContextPanel({storyId}:{storyId:string}){
 const [indicator,setIndicator]=useState<Indicator>('kosis_cpi');
 const [file,setFile]=useState<File|null>(null);const [consent,setConsent]=useState(false);
 const [fileError,setFileError]=useState('');const input=useRef<HTMLInputElement>(null);
 const [preview,setPreview]=useState('');
 const statistics=useMutation({mutationFn:(selected:Indicator)=>publicContext(storyId,selected)});
 const vision=useMutation({mutationFn:async()=>{
  if(!file)throw new Error('분석할 이미지를 선택해주세요.');
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(const byte of bytes)binary+=String.fromCharCode(byte);
  return imageEvidence(storyId,btoa(binary),file.type as 'image/png'|'image/jpeg',consent);
 }});
 useEffect(()=>{if(!file){setPreview('');return;}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 const select=(next:File|null)=>{
  vision.reset();setConsent(false);setFile(null);setFileError('');
  if(!next)return;
  if(!['image/png','image/jpeg'].includes(next.type)||next.size>1_000_000){setFileError('1MB 이하의 PNG/JPEG 이미지만 선택해주세요.');return;}
  setFile(next);
 };
 return <section className="reading-analysis evidence-context" aria-label="원문 밖의 자료 확인">
  <header className="reading-section-header"><h3>자료를 함께 확인하기</h3><p>공식 통계와 이미지 관찰을 기사 내용과 구분해 살펴보세요.</p></header>
  <div className="reading-card">
   <h4>공식 통계 맥락</h4><p>직접 선택한 대한민국 지표입니다. 이 기사의 주장을 검증하거나 관련성을 자동 판정한 결과가 아닙니다.</p>
   <label htmlFor="context-indicator">확인할 지표</label>
   <select id="context-indicator" value={indicator} onChange={e=>{setIndicator(e.target.value as Indicator);statistics.reset();}}>
    <option value="kosis_cpi">KOSIS 소비자물가지수 · 월간 2020=100</option><option value="inflation">World Bank 물가 상승률 · 연간 %</option><option value="population">World Bank 총인구 · 명</option><option value="gdp">World Bank 명목 GDP · 현재 US$</option>
   </select>
   <button className="reading-primary-button" disabled={statistics.isPending} onClick={()=>statistics.mutate(indicator)}>{statistics.isPending?'통계 조회 중…':'공식 통계 조회'}</button>
   {statistics.isError&&<p role="alert">{statistics.error.message}</p>}
   {statistics.data&&<div aria-live="polite">
    <h4>{statistics.data.data.title}</h4><p>{statistics.data.data.country} · {statistics.data.data.frequency} · {statistics.data.data.unit}</p>
    <ul>{statistics.data.data.observations.map(row=><li key={row.period}>{row.period}: {new Intl.NumberFormat('ko-KR',{maximumFractionDigits:3}).format(row.value)} ({statistics.data.data.unit})</li>)}</ul>
    <p className="small muted">제공기관: {statistics.data.data.provider}<br/>원출처 갱신일: {statistics.data.data.source_updated_at||'확인 불가'}<br/>조회 시각: {new Date(statistics.data.data.retrieved_at).toLocaleString('ko-KR')}</p>
    <p>{statistics.data.data.notice}</p><a className="reading-source-button" href={statistics.data.data.source_url} target="_blank" rel="noreferrer">공식 출처 확인 ↗</a>
   </div>}
  </div>
  <div className="reading-card">
   <h4>이미지 근거 읽기</h4><p>직접 선택한 이미지의 보이는 내용과 글자를 읽습니다. 기사와의 관련성·인물 신원·이미지 진위는 판정하지 않습니다.</p>
   <label htmlFor="evidence-image">확인할 이미지 · PNG/JPEG, 1MB·400만 화소 이하</label>
   <input id="evidence-image" ref={input} type="file" accept="image/png,image/jpeg" disabled={vision.isPending} onChange={e=>select(e.target.files?.[0]||null)}/>
   {file&&<p>선택됨: {file.name}</p>}{preview&&<img className="evidence-image-preview" src={preview} alt="직접 선택한 분석 대상 이미지"/>}{fileError&&<p role="alert">{fileError}</p>}
   <label className="vision-consent"><input type="checkbox" checked={consent} disabled={vision.isPending} onChange={e=>setConsent(e.target.checked)}/>선택 이미지가 설정된 AI 제공자에게 전송됨을 확인했습니다. 개인정보·비공개 자료를 넣지 않겠습니다.</label>
   <p className="small muted">이미지를 서버에 저장하지 않습니다. 외부 AI 제공자의 처리 정책은 별도이며, 판독에 비용이 발생할 수 있습니다.</p>
   <button className="reading-primary-button" disabled={!file||!consent||vision.isPending} onClick={()=>vision.mutate()}>{vision.isPending?'이미지 확인 중…':'이미지 읽기'}</button>
   {vision.isError&&<p role="alert">{vision.error.message}</p>}
   {vision.data&&<div aria-live="polite"><h4>이미지에서 관찰한 내용</h4><p>{vision.data.output.observation}</p><h4>읽을 수 있는 글자</h4>{vision.data.output.visible_text.length?<ul>{vision.data.output.visible_text.map((s,i)=><li key={i}>{s}</li>)}</ul>:<p>확실히 읽을 수 있는 글자가 없습니다.</p>}<ul>{vision.data.output.limitations.map((s,i)=><li key={i}>{s}</li>)}</ul><p className="small muted">{vision.data.notice}<br/>모델: {vision.data.model} · {vision.data.external_processing?'외부 AI 처리':'로컬 AI 처리'}</p></div>}
  </div>
 </section>;
}
