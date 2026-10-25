import type {FeedItem} from '../api/types';
// 페이지 경계에서 같은 사건이 재수신되어도 카드와 React 키를 중복시키지 않습니다.
export function uniqueFeedItems(items:FeedItem[]):FeedItem[]{
 const seen=new Set<string>();return items.filter(item=>{if(seen.has(item.story.id))return false;seen.add(item.story.id);return true;});
}
