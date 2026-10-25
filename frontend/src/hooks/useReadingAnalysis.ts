import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {requestReading,type ReadingMode} from '../api/reading';

export function useReadingAnalysis(storyId:string,mode:ReadingMode){
 const client=useQueryClient();const key=mode==='perspectives'?['reading-mode',storyId,mode,'comparison-v3']:['reading-mode',storyId,mode];
 const query=useQuery({queryKey:key,queryFn:()=>requestReading(storyId,mode),retry:false});
 // 생성 성공 시 같은 조회 캐시를 갱신해 탭에 즉시 표시합니다.
 const generate=useMutation({mutationFn:()=>requestReading(storyId,mode,true),onSuccess:value=>client.setQueryData(key,value)});
 return {query,generate};
}
