import {apiOrigin} from './client';
import type {components} from './workspace-schema';
export type ReadingResult=components['schemas']['ReadingResponse'];
export type ReadingMode=ReadingResult['mode'];

// 조회와 생성을 분리해 화면을 열기만 해서는 유료 모델을 호출하지 않습니다.
export async function requestReading(storyId:string,mode:ReadingMode,generate=false):Promise<ReadingResult>{
 const r=await fetch(`${apiOrigin}/api/local/stories/${encodeURIComponent(storyId)}/reading/${mode}`,{method:generate?'POST':'GET'});
 const value=await r.json();if(!r.ok)throw new Error(value.error?.message||value.detail||'분석 결과를 읽지 못했습니다.');return value;
}
