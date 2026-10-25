import {describe,expect,it} from 'vitest';
import {articleParagraphs} from './articleParagraphs';

describe('article reading layout',()=>{
  it('groups a long flat article into short paragraphs without changing its words',()=>{
    const text='지원 기간은 3개월입니다. 기준 금리는 3.5%입니다. 예산은 1,234.5억 원입니다. 추가 발표는 다음 주입니다. 확인된 사실만 제공했습니다. 마지막 문장입니다.';
    const paragraphs=articleParagraphs(text);
    expect(paragraphs.length).toBeGreaterThan(1);
    expect(paragraphs.join(' ')).toBe(text);
    expect(paragraphs.join(' ')).toContain('3.5%');
  });
  it('preserves provided paragraph breaks and treats markup as plain text',()=>{
    expect(articleParagraphs('<앵커> 첫 내용입니다.\r\n\r\n<기자> 다음 내용입니다.')).toEqual(['<앵커> 첫 내용입니다.','<기자> 다음 내용입니다.']);
    expect(articleParagraphs('   ')).toEqual([]);
  });
});
