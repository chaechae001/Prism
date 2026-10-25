import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { accountRequest, type AccountUser, type AccountSession, type AccountSignup } from '../../api/account';
import { apiMode } from '../../api/client';
import type { NewsThread, NewsComment } from '../../hooks/useSocialWorkspace';

type User = AccountUser;
type Workspace = { bookmarks: string[]; threads: NewsThread[]; comments: NewsComment[] };
const empty: Workspace = { bookmarks: [], threads: [], comments: [] };
type Account = {
  enabled:boolean;
  user: User | null; configured: boolean; loading: boolean; error: string;
  workspace: Workspace;
  authenticate: (email: string, password: string, signup: boolean) => Promise<'signed_in'|'confirmation_required'|'error'>;
  logout: () => Promise<void>; reload: () => Promise<void>;
  mutate: (path: string, method: string, body?: unknown) => void;
};
const Context = createContext<Account>({ enabled:false,user: null, configured: false, loading: false, error: '', workspace: empty,
  authenticate: async () => 'error', logout: async () => {}, reload: async () => {}, mutate: () => {} });
export const useAccount = () => useContext(Context);

export function AccountProvider({ children }: { children: ReactNode }) {
  // 서버가 명시적으로 허용한 경우에만 계정 화면을 엽니다.
  const [enabled,setEnabled]=useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(apiMode === 'http');
  const [error, setError] = useState('');
  const [workspace, setWorkspace] = useState(empty);
  const epoch = useRef(0);
  const queue = useRef(Promise.resolve());
  const reload = useCallback(async () => {
    const version = epoch.current;
    try {
      const value = await accountRequest<Workspace>('/workspace');
      if (version === epoch.current) { setWorkspace(value); setError(''); }
    } catch (e) {
      if (version === epoch.current) setError(e instanceof Error ? e.message : '계정 기록을 불러오지 못했습니다.');
      throw e;
    }
  }, []);
  useEffect(() => {
    if (apiMode !== 'http') return;
    let live = true;
    void accountRequest<AccountSession>('/session').then(async (s) => {
      if (!live) return;
      setEnabled(s.enabled ?? true); setConfigured(s.configured); setUser(s.user);
      if (s.user) await reload();
    }).catch((e: Error) => { if (live) setError(e.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; epoch.current++; };
  }, [reload]);
  useEffect(() => {
    if (!user) return;
    const timer = setInterval(() => {
      if (!document.hidden) void reload().catch((e: Error) => setError(e.message));
    }, 30000);
    return () => clearInterval(timer);
  }, [user, reload]);
  const mutate = (path: string, method: string, body?: unknown) => {
    const version = epoch.current;
    queue.current = queue.current.then(async () => {
      if (version !== epoch.current) return;
      await accountRequest(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      if (version === epoch.current) { await reload(); setError(''); }
    }).catch((e: Error) => { if (version === epoch.current) setError(e.message); });
  };
  const authenticate = async (email: string, password: string, signup: boolean) => {
    setLoading(true); setError(''); epoch.current++; setWorkspace(empty);
    try {
      const s = await accountRequest<AccountSignup>(signup ? '/signup' : '/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      if (s.confirmation_required) return 'confirmation_required' as const;
      setUser(s.user); await reload(); return 'signed_in' as const;
    } catch (e) { setError(e instanceof Error ? e.message : '로그인에 실패했습니다.'); return 'error' as const; }
    finally { setLoading(false); }
  };
  const logout = async () => {
    setLoading(true);
    try {
      await accountRequest('/logout', { method: 'POST' });
      epoch.current++; setUser(null); setWorkspace(empty); setError('');
    } catch (e) { setError(e instanceof Error ? e.message : '로그아웃에 실패했습니다.'); }
    finally { setLoading(false); }
  };
  return <Context.Provider value={{ enabled,user, configured, loading, error, workspace, authenticate, logout, reload, mutate }}>{children}</Context.Provider>;
}
