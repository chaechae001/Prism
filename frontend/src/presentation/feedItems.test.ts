import {expect,it} from 'vitest';
import {uniqueFeedItems} from './feedItems';
import {stories} from '../mocks/policy';
it('deduplicates event cards across pages while keeping ranking order',()=>{const item=(story:typeof stories[number])=>({story,reason:{code:'latest' as const,label:'최근'}});const rows=[item(stories[0]),item(stories[1]),item(stories[0])];expect(uniqueFeedItems(rows).map(row=>row.story.id)).toEqual([stories[0].id,stories[1].id]);expect(rows).toHaveLength(3);});
