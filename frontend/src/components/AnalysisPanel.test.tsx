import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalysisPanel } from "./AnalysisPanel";

describe("analysis availability for saved local clusters", () => {
  it.each(["five_w", "easy", "sentiment"] as const)("does not direct local %s analysis to disabled chat", (mode) => {
    const html = renderToStaticMarkup(<AnalysisPanel mode={mode} clusterPreview />);
    expect(html).toContain("추가 분석 결과를 준비하고 있습니다");
    expect(html).toContain("출처 탭에서 원문을 확인해주세요");
    expect(html).not.toContain("요청할 수 있어요");
  });
  it("preserves the existing analysis guidance for other sources", () => {
    const html = renderToStaticMarkup(<AnalysisPanel mode="easy" />);
    expect(html).toContain("뉴스 DM에서 요약이나 쉬운 설명을 요청할 수 있어요");
  });
});


describe('source grounded reading',()=>{
 it('renders cached evidence and clearly distinguishes a single source',()=>{
  const client=new QueryClient();client.setQueryData(['reading-mode','db-cluster-test','perspectives','comparison-v3'],{mode:'perspectives',source_count:1,notice:'AI 분석',cached:true,output:{items:[{label:'정책 쟁점',text:'정책을 논의합니다.',evidence:[{article_id:'a',quote:'<script>실행 금지</script>'}]}],limitations:['출처가 하나입니다.']}});
  const html=renderToStaticMarkup(<QueryClientProvider client={client}><AnalysisPanel mode="perspectives" storyId="db-cluster-test"/></QueryClientProvider>);
  expect(html).toContain('현재 출처는 1개입니다');expect(html).toContain('근거 기사 보기');expect(html).not.toContain('<script>');expect(html).toContain('&lt;script&gt;');
 });
});


it('shows real comparison axes separately from article focus',()=>{
 const client=new QueryClient();const evidence=[{article_id:'a',quote:'첫 근거'},{article_id:'b',quote:'둘째 근거'}];
 client.setQueryData(['reading-mode','db-cluster-compare','perspectives','comparison-v3'],{mode:'perspectives',source_count:2,article_count:2,comparison_kind:'cross_publisher',sources:[],notice:'AI 분석',cached:true,output:{items:[],limitations:[],comparison:{relation:'comparable',common_ground:[{label:'공통 사실',text:'같은 일정',evidence}],differences:[{label:'강조점 차이',text:'비용과 효과',evidence}]}}});
 const html=renderToStaticMarkup(<QueryClientProvider client={client}><AnalysisPanel mode="perspectives" storyId="db-cluster-compare"/></QueryClientProvider>);
 expect(html).toContain('공통으로 확인되는 내용');expect(html).toContain('같은 쟁점에서 달라지는 강조점');expect(html).toContain('비용과 효과');
});
