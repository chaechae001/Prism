import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {requestReading,type ReadingMode} from '../api/reading';

export function readingQueryOptions(storyId:string,mode:ReadingMode,revision?:string){
 return {queryKey:['reading-mode',storyId,mode,mode==='five_w'?'five-w-v4':mode==='perspectives'?'contrast-v5':mode==='sentiment'?'article-tone-v3':'v1',revision],
  queryFn:()=>requestReading(storyId,mode),retry:false as const,staleTime:Infinity};
}

export function useReadingAnalysis(storyId:string,mode:ReadingMode,revision?:string){
 const client=useQueryClient();const options=readingQueryOptions(storyId,mode,revision);const key=options.queryKey;
 const query=useQuery(options);
 // 생성 성공 시 같은 조회 캐시를 갱신해 탭에 즉시 표시합니다.
 const generate=useMutation({mutationFn:()=>requestReading(storyId,mode,true),onSuccess:value=>client.setQueryData(key,value)});
 return {query,generate};
}
