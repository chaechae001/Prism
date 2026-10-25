import {afterEach,expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {FeedContinuation} from './FeedContinuation';
afterEach(()=>vi.unstubAllGlobals());
const props={hasNextPage:true,fetching:false,error:null,loadedCount:6,paused:false,load:vi.fn().mockResolvedValue(undefined)};
it('uses a sentinel instead of a normal load more button',()=>{vi.stubGlobal('IntersectionObserver',class{});const html=renderToStaticMarkup(<FeedContinuation {...props}/>);expect(html).toContain('feed-sentinel');expect(html).not.toContain('<button');});
it('offers an explicit retry after a page fails',()=>{const html=renderToStaticMarkup(<FeedContinuation {...props} error={new Error('offline')}/>);expect(html).toContain('읽던 기사는 그대로');expect(html).toContain('다시 불러오기');});
it('announces the end instead of loading forever',()=>{const html=renderToStaticMarkup(<FeedContinuation {...props} hasNextPage={false}/>);expect(html).toContain('마지막까지');});
