import { useState } from 'react';
import { useAccount } from './AccountProvider';
import { accountRequest } from '../../api/account';

export function AccountPanel() {
  const account = useAccount();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [signup, setSignup] = useState(false);
  const [resending,setResending]=useState(false);
  const [resendError,setResendError]=useState('');
  const [cooldown,setCooldown]=useState(false);
  const [notice, setNotice] = useState(() => {
    const result = new URL(location.href).searchParams.get('auth');
    return result === 'return' ? '인증 링크에서 돌아왔습니다. 가입한 이메일과 비밀번호로 로그인해주세요.'
      : result === 'error' ? '인증 링크가 만료되었거나 처리되지 않았습니다. 이미 인증했다면 로그인해보세요.' : '';
  });
  if(!account.enabled&&!account.loading) return <section className="account-panel" aria-label="테스트 모드"><h2>로그인 없이 둘러보기</h2><p>계정 기능은 추후 제공할 예정입니다. 지금은 북마크·댓글·대화를 이 브라우저에 저장합니다.</p></section>;
  return <section className="account-panel" aria-label="내 계정">
    {account.user ? <>
      <strong>{account.user.email}</strong>
      <p>북마크·나만의 댓글·뉴스 대화를 계정에 저장합니다.</p>
      <button onClick={() => void account.reload().catch(() => {})}>저장 기록 다시 불러오기</button>
      <button disabled={account.loading} onClick={() => void account.logout()}>로그아웃</button>
    </> : <>
      <h2>어디서든 나의 뉴스</h2>
      <p>로그인하면 다른 기기에서도 저장한 뉴스와 대화를 이어서 볼 수 있어요. 기존 브라우저 기록은 자동 업로드하지 않습니다.</p>
      <form onSubmit={async (e) => {
        e.preventDefault(); setNotice('');
        const result = await account.authenticate(email, password, signup);
        setPassword('');
        if (result === 'confirmation_required') setNotice('가입 요청을 처리했습니다. 인증이 필요한 계정은 메일함·스팸함을 확인해주세요. 이미 인증했다면 로그인해주세요.');
      }}>
        <label>이메일<input autoComplete="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>비밀번호<input autoComplete={signup ? 'new-password' : 'current-password'} type="password" required minLength={8} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button disabled={account.loading || !account.configured}>{account.loading ? '확인 중…' : signup ? '회원가입' : '로그인'}</button>
        <button type="button" onClick={() => { setSignup(!signup); setNotice(''); }}>{signup ? '로그인으로 돌아가기' : '처음이라면 회원가입'}</button>
      </form>
      <button disabled={resending||cooldown||!account.configured||!email.trim()} onClick={async()=>{
        setResendError('');setNotice('');
        if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())){setResendError('수신 가능한 이메일 주소를 입력해주세요.');return;}
        setResending(true);
        try{const r=await accountRequest<{notice:string}>('/resend',{method:'POST',body:JSON.stringify({email:email.trim()})});setNotice(r.notice);setCooldown(true);setTimeout(()=>setCooldown(false),60000);}
        catch(e){setResendError(e instanceof Error?e.message:'메일을 요청하지 못했습니다.');}
        finally{setResending(false);}
      }}>{resending?'요청 중…':cooldown?'잠시 후 다시 요청할 수 있어요':'인증 메일 다시 요청'}</button>
      <p>이미 가입한 이메일이라면 로그인해주세요. 메일이 계속 오지 않으면 발송 제한 또는 메일 서버 설정을 확인해야 합니다.</p>
      {!account.configured && !account.loading && <p role="status">로그인 연결 설정을 확인해주세요. 로그인 전에는 브라우저에 저장합니다.</p>}
    </>}
    {account.error && <p role="alert">{account.error}</p>}
    {resendError && <p role="alert">{resendError}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
