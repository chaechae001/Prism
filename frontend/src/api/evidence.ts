import {apiOrigin} from './client';
import type {components} from './workspace-schema';
export type PublicContext=components['schemas']['ContextResponse'];
export type VisionResult=components['schemas']['VisionResponse'];
export type Indicator='kosis_cpi'|'inflation'|'population'|'gdp';

async function response<T>(url:string,options?:RequestInit):Promise<T>{
 const r=await fetch(`${apiOrigin}${url}`,options);const value=await r.json();
 if(!r.ok)throw new Error(value.error?.message||value.detail||'자료를 확인하지 못했습니다.');
 return value;
}
export const publicContext=(storyId:string,indicator:Indicator)=>response<PublicContext>(`/api/local/stories/${encodeURIComponent(storyId)}/public-context?indicator=${indicator}`);
export const imageEvidence=(storyId:string,image_base64:string,media_type:'image/png'|'image/jpeg',consent_external:boolean)=>response<VisionResult>(`/api/local/stories/${encodeURIComponent(storyId)}/image-evidence`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64,media_type,consent_external})});
