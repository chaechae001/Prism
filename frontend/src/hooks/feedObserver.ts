/** One page per observation cycle; React reattaches after data settles. */
export function observeFeedEnd(target:Element,load:()=>Promise<unknown>):()=>void{
 let active=true;let started=false;
 const observer=new IntersectionObserver(entries=>{
  if(!active||started||!entries.some(entry=>entry.isIntersecting))return;
  started=true;
  // 페이지 오류는 Query 상태로 전달합니다. 자동 재시도로 요청을 반복하지 않습니다.
  void Promise.resolve().then(()=>active?load():undefined).catch(()=>{});
 },{rootMargin:'600px 0px',threshold:0});
 observer.observe(target);
 return ()=>{active=false;observer.disconnect();};
}
