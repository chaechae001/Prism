import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {observeFeedEnd} from './feedObserver';
let notify:IntersectionObserverCallback;let options:IntersectionObserverInit;const disconnect=vi.fn();const observe=vi.fn();
beforeEach(()=>{disconnect.mockClear();observe.mockClear();vi.stubGlobal('IntersectionObserver',class{constructor(cb:IntersectionObserverCallback,value:IntersectionObserverInit){notify=cb;options=value;}observe=observe;disconnect=disconnect;});});
afterEach(()=>vi.unstubAllGlobals());
const entry=(isIntersecting:boolean)=>[{isIntersecting} as IntersectionObserverEntry];
describe('feed end observation',()=>{
 it('preloads one page near the end and prevents repeated notifications',async()=>{const load=vi.fn().mockResolvedValue(undefined);const dispose=observeFeedEnd({} as Element,load);notify(entry(false),{} as IntersectionObserver);await Promise.resolve();expect(load).not.toHaveBeenCalled();notify(entry(true),{} as IntersectionObserver);notify(entry(true),{} as IntersectionObserver);await Promise.resolve();expect(load).toHaveBeenCalledTimes(1);expect(options.rootMargin).toBe('600px 0px');dispose();expect(disconnect).toHaveBeenCalledOnce();});
 it('does not start a queued request after cleanup',async()=>{const load=vi.fn().mockResolvedValue(undefined);const dispose=observeFeedEnd({} as Element,load);notify(entry(true),{} as IntersectionObserver);dispose();await Promise.resolve();expect(load).not.toHaveBeenCalled();});
 it('does not retry a failed page automatically',async()=>{const load=vi.fn().mockRejectedValue(new Error('offline'));observeFeedEnd({} as Element,load);notify(entry(true),{} as IntersectionObserver);await Promise.resolve();await Promise.resolve();notify(entry(true),{} as IntersectionObserver);expect(load).toHaveBeenCalledTimes(1);});
});
