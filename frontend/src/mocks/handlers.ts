import { delay, http, HttpResponse } from 'msw';
import { makeFeed, MockValidationError, stories, version } from './policy';

const error=(status:number,code:string,message:string)=>HttpResponse.json({error:{code,message,details:[],request_id:crypto.randomUUID()}},{status});
export const handlers=[
  http.get('*/health',()=>HttpResponse.json({status:'ok',mode:'mock',dataset_version:version})),
  http.get('*/api/v1/categories',()=>HttpResponse.json({items:Object.entries({politics:'정치',economy:'경제',society:'사회',technology:'기술'}).map(([id,label])=>({id,label,count:stories.filter(s=>s.category===id).length}))})),
  http.get('*/api/v1/stories',async({request})=>{
    const scenario=request.headers.get('X-Mock-Scenario')||'normal';
    await delay(scenario==='slow'?2000:300);
    if(scenario==='error') return error(503,'MOCK_ERROR','테스트용 API 오류입니다.');
    try{return HttpResponse.json(makeFeed(new URL(request.url),scenario));}
    catch(e){if(e instanceof MockValidationError) return error(422,'VALIDATION_ERROR',e.message); throw e;}
  }),
  http.get('*/api/v1/stories/:id',async({params})=>{
    await delay(150);
    const story=stories.find(s=>s.id===params.id);
    return story?HttpResponse.json({story,request_id:crypto.randomUUID(),is_mock:true}):error(404,'NOT_FOUND','해당 사건을 찾을 수 없습니다.');
  }),
  http.post('*/api/v1/feedback',async({request})=>{
    await delay(200);
    let body:unknown; try{body=await request.json();}catch{return error(422,'VALIDATION_ERROR','JSON 본문을 확인해주세요.');}
    if(!body || typeof body!=='object'||Array.isArray(body)) return error(422,'VALIDATION_ERROR','요청 값을 확인해주세요.');
    const b=body as Record<string,unknown>;
    if(Object.keys(b).some(k=>!['story_id','kind','comment'].includes(k))||typeof b.story_id!=='string'||!['useful','more_perspectives','report_error'].includes(String(b.kind))|| (b.comment!==undefined && b.comment!==null && (typeof b.comment!=='string'||b.comment.length>500))) return error(422,'VALIDATION_ERROR','요청 값을 확인해주세요.');
    if(!stories.some(s=>s.id===b.story_id)) return error(404,'NOT_FOUND','해당 사건을 찾을 수 없습니다.');
    return HttpResponse.json({id:crypto.randomUUID(),status:'accepted',persisted:false,request_id:crypto.randomUUID()},{status:201});
  }),
  // Administrative tokens must never be bundled into browser code.
  http.all('*/api/v1/internal/*',()=>error(401,'UNAUTHORIZED','관리자 Mock API는 FastAPI 서버에서 테스트해주세요.')),
];
