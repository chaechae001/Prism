import {afterEach,expect,it,vi} from 'vitest';
import {publicContext,imageEvidence} from './evidence';
afterEach(()=>vi.unstubAllGlobals());
it('statistics use GET and an encoded story ID, never the image endpoint',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response('{"story_id":"a"}'));vi.stubGlobal('fetch',fetch);
 await publicContext('a/b','population');
 expect(fetch.mock.calls[0][0]).toContain('/a%2Fb/public-context?indicator=population');
 expect(fetch.mock.calls[0][1]).toBeUndefined();
});
it('image bytes and explicit consent are sent only through POST',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response('{}'));vi.stubGlobal('fetch',fetch);
 await imageEvidence('a','base64-fixture','image/png',true);
 expect(fetch.mock.calls[0][1].method).toBe('POST');
 expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({image_base64:'base64-fixture',media_type:'image/png',consent_external:true});
});
it('provider failure is surfaced without a successful-looking replacement',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"error":{"message":"통계 조회 실패"}}',{status:502})));
 await expect(publicContext('a','inflation')).rejects.toThrow('통계 조회 실패');
});
