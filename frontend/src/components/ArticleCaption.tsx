import { useId,useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown } from 'lucide-react';
import { apiMode,apiOrigin } from '../api/client';
import type { Story } from '../api/types';
import type { components } from '../api/workspace-schema';
import { isDbClusterStory } from '../presentation/clusterPreview';
import { articleParagraphs } from '../presentation/articleParagraphs';

type Body=components['schemas']['ArticleBody'];
export function CaptionText({label,text}:{label:string;text:string}) {
  const [expanded,setExpanded]=useState(false);
  const id=useId();const paragraphs=articleParagraphs(text);
  return <section className="article-caption" aria-label={label}><span className="article-caption-label">{label}</span>
    <div id={id}>{expanded?<div className="article-paragraphs">{paragraphs.map((p,i)=><p key={i}>{p}</p>)}</div>:<p className="post-caption">{paragraphs.slice(0,2).join(' ')}</p>}</div>
    {(text.length>90||paragraphs.length>1)&&<button className="caption-more" aria-controls={id} aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?'접기':'본문 더 읽기'}<ChevronDown size={12}/></button>}</section>;
}

function ConnectedCaption({story}:{story:Story}) {
  const query=useQuery({queryKey:['local-body',story.id,story.updated_at],queryFn:async({signal})=>{
    const r=await fetch(`${apiOrigin}/api/local/stories/${encodeURIComponent(story.id)}/body`,{signal});
    const value=await r.json();
    if(!r.ok) throw new Error(value.error?.message||'본문을 불러오지 못했습니다.');
    return value as Body;
  },retry:false,staleTime:60000});
  if(query.isPending) return <p className="post-caption" role="status">기사 내용을 불러오는 중…</p>;
  if(query.error) return <p className="post-caption">본문을 불러오지 못했습니다. 아래 원문 링크에서 읽을 수 있어요. <button onClick={()=>void query.refetch()}>다시 시도</button></p>;
  return <CaptionText label={query.data.is_excerpt?'기사 본문 발췌':'기사 본문'} text={query.data.text}/>;
}

export function ArticleCaption({story,ready,clusterPreview}:{story:Story;ready:boolean;clusterPreview:boolean}) {
  if(apiMode==='http'&&isDbClusterStory(story)) return <ConnectedCaption story={story}/>;
  return <CaptionText label={ready?'AI 요약':isDbClusterStory(story)?'대표기사 · 원문 출처':clusterPreview?'대표기사 발췌':'기사 내용'} text={ready?story.summary.bullets.map(b=>b.text).join(' ')||story.dek:story.dek}/>;
}
