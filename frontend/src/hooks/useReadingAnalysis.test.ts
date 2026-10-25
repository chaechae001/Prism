import {QueryClient,QueryObserver} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {readingQueryOptions} from './useReadingAnalysis';
import type {ReadingResult} from '../api/reading';

const generated:ReadingResult={story_id:'db-cluster-test',mode:'five_w',cached:false,source_count:1,
 model:'test',prompt_version:'test',notice:'test',article_count:1,unique_body_count:1,
 comparison_kind:'single_article',sources:[],output:{items:[{label:'무엇',text:'확인된 사실',evidence:[{article_id:'a',quote:'확인된 원문 근거'}]}],limitations:[],comparison:null}};

it('keeps a generated result when a dialog remounts and another server has no cache',()=>{
 const client=new QueryClient();
 const fetcher=vi.fn().mockResolvedValue({...generated,output:null});
 const options={...readingQueryOptions(generated.story_id,'five_w','revision-1'),queryFn:fetcher};
 client.setQueryData(options.queryKey,generated);
 const observer=new QueryObserver(client,options);
 const unsubscribe=observer.subscribe(()=>{});
 expect(fetcher).not.toHaveBeenCalled();
 expect(observer.getCurrentResult().data?.output?.items[0].text).toBe('확인된 사실');
 unsubscribe();client.clear();
});

it('loads a changed article revision rather than reusing the old result',async()=>{
 const client=new QueryClient();
 const old=readingQueryOptions(generated.story_id,'five_w','revision-1');
 client.setQueryData(old.queryKey,generated);
 const fetcher=vi.fn().mockResolvedValue({...generated,output:null});
 const value=await client.fetchQuery({...readingQueryOptions(generated.story_id,'five_w','revision-2'),queryFn:fetcher});
 expect(fetcher).toHaveBeenCalledOnce();expect(value.output).toBeNull();client.clear();
});
