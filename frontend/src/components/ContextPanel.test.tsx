import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {ContextPanel} from './ContextPanel';
import * as evidence from '../api/evidence';
vi.mock('../api/evidence',()=>({publicContext:vi.fn(),imageEvidence:vi.fn()}));
it('opening the panel does not fetch statistics or invoke the image model',()=>{
 const client=new QueryClient();
 const html=renderToStaticMarkup(<QueryClientProvider client={client}><ContextPanel storyId="story-a"/></QueryClientProvider>);
 expect(evidence.publicContext).not.toHaveBeenCalled();expect(evidence.imageEvidence).not.toHaveBeenCalled();
 expect(html).toContain('직접 선택한 대한민국 지표');
 expect(html).toContain('기사와의 관련성·인물 신원·이미지 진위는 판정하지 않습니다');
 expect(html).toMatch(/disabled="">이미지 읽기/);
 expect(html).toContain('외부 AI 제공자의 처리 정책은 별도');
 client.clear();
});
