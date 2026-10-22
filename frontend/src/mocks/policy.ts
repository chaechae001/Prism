import fixtures from '../../../contracts/fixtures.json';
import type { FeedItem, FeedResponse, Mode, Story } from '../api/types';

export const stories = fixtures.stories as Story[];
export const version = fixtures.dataset_version;
export const labels = {latest:'최근에 업데이트된 사건',public_interest:'함께 살펴볼 주요 이슈',source_diversity:'여러 출처를 비교할 수 있어요',discovery:'주제의 폭을 넓히는 발견'};
const count = (map: Map<string,number>,key:string) => map.get(key) || 0;
const bump = (map: Map<string,number>,key:string) => map.set(key,count(map,key)+1);
const cmp = (a:string,b:string) => a < b ? -1 : a > b ? 1 : 0;
export function rank(input: Story[], mode: Mode, diversity: number) {
  const latest = [...input].sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at)||cmp(a.id,b.id));
  if(mode==='latest') return {items:latest.map(story=>({story,reason:{code:'latest' as const,label:labels.latest}})),relaxed:false};
  const categories = new Map<string,number>(), publishers = new Map<string,number>(), leads = new Map<string,number>();
  const fresh = new Map(latest.map((s,i)=>[s.id,1-i/Math.max(1,latest.length)]));
  const pool=[...latest], items:FeedItem[]=[];
  let relaxed=false;
  const weight=diversity/100;
  const score=(s:Story)=>{
    const sources=[...new Set(s.articles.map(a=>a.publisher_id))];
    const overlap=sources.reduce((sum,p)=>sum+count(publishers,p),0)/sources.length;
    const bonus=mode==='explore' && count(categories,s.category)===0?.25:0;
    return .65*s.public_interest+.35*fresh.get(s.id)!-weight*(.3*count(categories,s.category)+.1*overlap)+weight*bonus;
  };
  while(pool.length){
    let candidates=diversity>=50?pool.filter(s=>count(leads,s.articles[0].publisher_id)<2):pool;
    if(!candidates.length){candidates=pool;relaxed=true;}
    const best=[...candidates].sort((a,b)=>score(b)-score(a)||cmp(a.id,b.id))[0];
    const code=items.length && !count(categories,best.category) && diversity>=50?'discovery':diversity>=50?'source_diversity':'public_interest';
    items.push({story:best,reason:{code,label:labels[code]}});
    bump(categories,best.category);
    new Set(best.articles.map(a=>a.publisher_id)).forEach(p=>bump(publishers,p));
    bump(leads,best.articles[0].publisher_id);
    pool.splice(pool.indexOf(best),1);
  }
  return {items,relaxed};
}

export class MockValidationError extends Error {}
function invalid(message='요청 값을 확인해주세요.'): never { throw new MockValidationError(message); }
export function makeFeed(url: URL, scenario='normal'): FeedResponse {
  const p=url.searchParams;
  const rawQuery=p.get('q')||'';
  if(rawQuery.length>100) invalid();
  const q=rawQuery.trim(), category=p.get('category')||'', mode=(p.get('mode')||'balanced') as Mode;
  if(category && !['politics','economy','society','technology'].includes(category)) invalid();
  if(!['balanced','latest','explore'].includes(mode)) invalid();
  const integer=(key:string,fallback:number,min:number,max:number)=>{
    const raw=p.get(key); if(raw!==null && !/^[-+]?\d+(\.0+)?$/.test(raw.trim())) invalid();
    const value=raw===null?fallback:Number(raw);
    return Number.isSafeInteger(value) && value>=min && value<=max?value:invalid();
  };
  const diversity=integer('diversity',70,0,100), limit=integer('limit',6,1,20);
  const pool=scenario==='empty'?[]:stories.filter(s=>(!category||s.category===category) && [s.title,s.dek,...s.keywords].join(' ').toLocaleLowerCase().includes(q.toLocaleLowerCase()));
  const {items,relaxed}=rank(pool,mode,diversity);
  const key=[version,q,category,mode,diversity];
  let offset=0;
  const cursor=p.get('cursor');
  if(cursor){
    if(cursor.length>1000) invalid();
    try {
      const normalized=cursor.replace(/-/g,'+').replace(/_/g,'/');
      const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(atob(normalized),c=>c.charCodeAt(0))));
      if(!Array.isArray(value)||value.length!==6||JSON.stringify(value.slice(0,5))!==JSON.stringify(key)||!Number.isInteger(value[5])||value[5]<=0||value[5]>items.length) invalid();
      offset=value[5];
    } catch {invalid('현재 검색 조건과 일치하지 않는 커서입니다.');}
  }
  const next=offset+limit<items.length?btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify([...key,offset+limit])))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''):null;
  const page=items.slice(offset,offset+limit);
  return {items:page,total:items.length,next_cursor:next,meta:{request_id:crypto.randomUUID(),generated_at:new Date().toISOString(),dataset_version:version,is_mock:true,mode,diversity,policy_version:'mock-v1',policy_notes:['개인화 없는 데모 순위입니다.','다양성은 주제와 출처 중복을 줄이는 가중치이며 정치 성향 점수가 아닙니다.','정렬은 고정된 fixture 최신성·공익성 예시 값을 사용합니다.'],returned_categories:[...new Set(page.map(i=>i.story.category))],source_cap_relaxed:relaxed}};
}
