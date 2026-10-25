import {useEffect,useRef} from 'react';
import {observeFeedEnd} from '../hooks/feedObserver';

type Props={hasNextPage:boolean;fetching:boolean;loadingNext?:boolean;error:Error|null;loadedCount:number;paused:boolean;load:()=>Promise<unknown>};
export function FeedContinuation({hasNextPage,fetching,loadingNext=fetching,error,loadedCount,paused,load}:Props){
 const sentinel=useRef<HTMLDivElement>(null);
 const supported=typeof IntersectionObserver!=='undefined';
 useEffect(()=>{
  if(!hasNextPage||fetching||error||paused||!supported||!sentinel.current)return;
  return observeFeedEnd(sentinel.current,load);
 },[hasNextPage,fetching,error,loadedCount,paused,load,supported]);
 return <div className="feed-continuation" aria-live="polite">
  <div ref={sentinel} className="feed-sentinel" aria-hidden="true"/>
  {loadingNext&&<p role="status">다음 뉴스를 불러오고 있습니다…</p>}
  {error?<div role="alert"><p>다음 뉴스를 불러오지 못했습니다. 읽던 기사는 그대로 볼 수 있어요.</p><button className="social-load-more" disabled={fetching||paused} onClick={()=>void load()}>다시 불러오기</button></div>
   :!hasNextPage&&loadedCount>0?<p>현재 뉴스의 마지막까지 읽었어요.</p>
   :!supported&&hasNextPage?<button className="social-load-more" disabled={fetching||paused} onClick={()=>void load()}>다음 뉴스 불러오기</button>:null}
 </div>;
}
