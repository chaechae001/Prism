import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {AnalysisPanel,ReadingResults} from './AnalysisPanel';
import type {ReadingResult} from '../api/reading';

const evidence=[{article_id:'a',quote:'즉시 도입해야 합니다.'},{article_id:'b',quote:'도입에 반대합니다.'}];
type Comparison=NonNullable<NonNullable<ReadingResult['output']>['comparison']>;
function data(mode:'perspectives'|'sentiment',differences:Comparison['differences']=[]):ReadingResult{
 return {story_id:'db-cluster-test',cached:true,source_count:2,model:'test',prompt_version:'test',article_count:2,unique_body_count:2,comparison_kind:'cross_publisher',mode,sources:[{id:'a',title:'찬성 기사',publisher:'가 매체'},{id:'b',title:'반대 기사',publisher:'나 매체'}],output:{items:[],limitations:['내부 검토 메모'],comparison:{relation:'comparable',common_ground:[],differences}},notice:'AI가 본문 근거를 정리한 결과입니다.'};
}
it('hides the deferred comparison even when the API contains comparison results',()=>{
 const value=data('perspectives',[{label:'도입 여부',text:'같은 정책에 대한 찬반',kind:'opposing_stances',positions:[{article_id:'a',text:'즉시 도입'},{article_id:'b',text:'도입 반대'}],evidence}]);
 const html=renderToStaticMarkup(<ReadingResults data={value} onCite={()=>{}}/>);
 expect(html).toBe('');
});
it('does not mount or request the deferred comparison panel',()=>{
 expect(renderToStaticMarkup(<AnalysisPanel mode="perspectives" storyId="db-cluster-test"/>)).toBe('');
});

it('shows easy-reading evidence and sources only once after the final explanation',()=>{
 const value={...data('sentiment'),mode:'easy' as const};
 value.output!.items=[{label:'핵심 내용',text:'첫 번째 쉬운 설명',evidence:[evidence[0]]},{label:'알아두기',text:'마지막 쉬운 설명',evidence}];
 const html=renderToStaticMarkup(<ReadingResults data={value} onCite={()=>{}}/>);
 expect(html.match(/<summary>/g)).toHaveLength(1);
 expect(html.match(/출처 보기 /g)).toHaveLength(1);
 expect(html.indexOf('<summary>')).toBeGreaterThan(html.indexOf('마지막 쉬운 설명'));
 expect(html.match(/즉시 도입해야 합니다\./g)).toHaveLength(1);
});

it('shows available 5W fields without inventing missing fields',()=>{
 const value={...data('sentiment'),mode:'five_w' as const};
 value.output!.items=[{label:'누가',text:'확인된 주체',evidence:[evidence[0]]},{label:'무엇',text:'확인된 내용',evidence:[evidence[0]]}];
 const html=renderToStaticMarkup(<ReadingResults data={value} onCite={()=>{}}/>);
 expect(html).toContain('원문에서 확인된 2개 항목');
 expect(html).toContain('확인된 주체');expect(html).toContain('확인된 내용');
 expect(html).not.toContain('>언제<');expect(html).not.toContain('>왜<');
});
it('renders one overall tone with a brief reason and collapsible evidence',()=>{
 const value=data('sentiment');value.output!.items=[{label:'중립·정보 전달',text:'공식 발표와 수치를 차분하게 전달합니다.',evidence:[{article_id:'a',quote:'<script>원문</script>'}]}];
 const html=renderToStaticMarkup(<ReadingResults data={value} onCite={()=>{}}/>);
 expect(html.match(/class="tone-card"/g)).toHaveLength(1);expect(html).toContain('공식 발표');expect(html).toContain('<details');expect(html).not.toContain('<script>');expect(html).not.toContain('아직 확인할 내용');
});
it('does not display internal readiness or ungenerated summary boxes',()=>{
 const html=renderToStaticMarkup(<AnalysisPanel mode="easy" clusterPreview/>);
 expect(html).not.toContain('준비하고 있습니다');expect(html).not.toContain('AI 요약을 생성하지 않았습니다');
});
