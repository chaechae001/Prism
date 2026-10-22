import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import { setupServer } from 'msw/node';
import { makeFeed, stories, rank, MockValidationError } from './policy';
import { handlers } from './handlers';
import parity from '../../../contracts/parity-cases.json';

describe('Mock and FastAPI contract parity',()=>{
  for(const c of parity) it(JSON.stringify(c.query),()=>{
    const url=new URL('https://mock.test/api/v1/stories');
    Object.entries(c.query).forEach(([k,v])=>{if(v!==undefined)url.searchParams.set(k,String(v));});
    const r=makeFeed(url);
    expect(r.items.map(i=>i.story.id)).toEqual(c.ids);
    expect(r.items.map(i=>i.reason.code)).toEqual(c.reasons);
    expect(r.total).toBe(c.total);
    expect(r.next_cursor).toBe(c.cursor);
  });
  it('cursors preserve Unicode and reject changed filters',()=>{
    const url=new URL('https://mock.test/api/v1/stories?q=지역&limit=1');
    const first=makeFeed(url);
    expect(first.next_cursor).toBeTruthy();url.searchParams.set('cursor',first.next_cursor!);
    expect(makeFeed(url).items[0].story.id).not.toBe(first.items[0].story.id);
    url.searchParams.set('category','politics');
    expect(()=>makeFeed(url)).toThrow(MockValidationError);
  });
  it('rejects invalid filters and has no duplicate pagination',()=>{
    for(const params of ['limit=0','diversity=101','limit=1.5','mode=bad','category=no','cursor=bad'])expect(()=>makeFeed(new URL(`https://mock.test/api/v1/stories?${params}`))).toThrow(MockValidationError);
    const ids=new Set<string>(), url=new URL('https://mock.test/api/v1/stories?limit=2');
    let more:string|null=null;
    do{if(more)url.searchParams.set('cursor',more);const r=makeFeed(url);for(const i of r.items){expect(ids.has(i.story.id)).toBe(false);ids.add(i.story.id);}more=r.next_cursor;}while(more);
    expect(ids.size).toBe(stories.length);
  });
  it('high diversity puts four available categories into the first four slots',()=>{
    expect(new Set(rank(stories,'balanced',100).items.slice(0,4).map(i=>i.story.category)).size).toBe(4);
  });
});

describe('MSW HTTP behavior',()=>{
  const server=setupServer(...handlers);
  beforeAll(()=>server.listen({onUnhandledRequest:'error'}));
  afterEach(()=>server.resetHandlers()); afterAll(()=>server.close());
  it('returns error, empty, detail 404 and validated feedback envelopes',async()=>{
    const url='https://mock.test/api/v1';
    expect((await fetch(`${url}/stories`,{headers:{'X-Mock-Scenario':'error'}})).status).toBe(503);
    expect((await (await fetch(`${url}/stories`,{headers:{'X-Mock-Scenario':'empty'}})).json()).items).toEqual([]);
    expect((await fetch(`${url}/stories/missing`)).status).toBe(404);
    const bad=await fetch(`${url}/feedback`,{method:'POST',body:JSON.stringify({story_id:'story-001',kind:'bad'})});
    expect(bad.status).toBe(422);
    const good=await fetch(`${url}/feedback`,{method:'POST',body:JSON.stringify({story_id:'story-001',kind:'useful'})});
    expect(good.status).toBe(201); expect((await good.json()).persisted).toBe(false);
  });
});
