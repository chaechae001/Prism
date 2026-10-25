import {afterEach,expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {AccountPanel} from './AccountPanel';

const state=vi.hoisted(()=>({enabled:false,loading:false}));
vi.mock('./AccountProvider',()=>({useAccount:()=>state}));
afterEach(()=>{state.loading=false;vi.unstubAllGlobals();});

it.each([false,true])('keeps authentication forms hidden while deferred (loading=%s)',loading=>{
 state.loading=loading;
 vi.stubGlobal('location',{href:'http://127.0.0.1:5186/?view=mypage'});
 const html=renderToStaticMarkup(<AccountPanel/>);
 expect(html).toContain('나의 뉴스 보관함');
 expect(html).toContain('다른 기기와 자동 동기화되지');
 expect(html).not.toContain('<form');
 expect(html).not.toContain('type="password"');
 expect(html).not.toContain('인증 메일 다시 요청');
});
