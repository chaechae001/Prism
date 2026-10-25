"""Deterministic, entirely fictional fixtures. Run from repository root."""
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = [
 ('story-001','technology','AI가 바꾸는 일터, 생산성 너머의 질문들','생산성의 기회와 일자리 전환의 과제를 함께 읽습니다.','chip',['AI','노동','생산성'],.97,'ready'),
 ('story-002','politics','도시의 내일을 결정할 새로운 교통 정책','이동의 편리함과 재정 부담, 정책의 서로 다른 쟁점을 살펴봅니다.','city',['교통','정책','도시'],.94,'ready'),
 ('story-003','economy','금리의 방향, 가계와 기업이 주목하는 이유','같은 금리 변화도 대출자와 예금자에게 다른 의미가 됩니다.','market',['금리','금융','가계'],.91,'ready'),
 ('story-004','society','학교 밖 배움, 지역이 교육의 공간이 된다','지역 연계 교육의 기회와 접근성 격차를 함께 살펴봅니다.','school',['교육','지역','접근성'],.88,'ready'),
 ('story-005','economy','에너지 전환의 속도와 비용 사이','투자 확대의 필요성과 소비자가 부담할 비용이 쟁점입니다.','energy',['에너지','투자','전환'],.85,'ready'),
 ('story-006','technology','반도체 투자, 기술 경쟁의 다음 장','공급망 안정과 자원 집중 문제를 서로 다른 시선으로 봅니다.','chip',['반도체','공급망','투자'],.89,'ready'),
 ('story-007','society','주 4일 근무 논의, 업종마다 다른 출발선','근로시간 단축과 현장의 운영 여건을 비교합니다.','work',['노동','근무','생산성'],.83,'ready'),
 ('story-008','politics','지역 예산, 시민의 참여는 어디까지','참여 확대의 기대와 대표성 확보의 과제를 살펴봅니다.','assembly',['예산','시민','지역'],.80,'ready'),
 ('story-009','technology','공공 연구 데이터 개방을 둘러싼 논의','데이터 활용과 개인정보 보호의 접점을 찾습니다.','research',['데이터','연구','개인정보'],.77,'pending'),
 ('story-010','society','지역 의료 공백, 현장이 제안한 대안','독립적인 추가 출처를 확보하기 전에는 통합 요약을 보류합니다.','city',['의료','지역','복지'],.79,'insufficient_sources'),
 ('story-011','economy','작은 기업의 수출, 새로운 시장을 찾아서','판로 확대의 기회와 환율·물류 부담을 함께 읽습니다.','market',['수출','기업','환율'],.75,'ready'),
 ('story-012','politics','공공 정보 공개 절차 개선 논의','요약 생성 오류로 원문 목록만 제공합니다.','assembly',['정보공개','행정','정책'],.71,'failed'),
]
publishers = [('p-01','데모 일보'),('p-02','데모 경제'),('p-03','데모 시민'),('p-04','데모 테크'),('p-05','데모 지역'),('p-06','데모 통신')]
stories = []
for n,(sid,category,title,dek,visual,tags,interest,status) in enumerate(rows):
    count = 1 if status == 'insufficient_sources' else 3 + n % 3
    articles=[]
    for j in range(count):
        pid,pname=publishers[(n+j)%len(publishers)]
        articles.append({'id':f'{sid}-a{j+1}','publisher_id':pid,'publisher_name':pname,
          'title':f'[가상 기사] {title} — '+['기회와 기대','현장의 과제','제도와 실행','지역의 시선','남은 질문'][j],
          'url':f'https://example.com/demo/{sid}/a{j+1}',
          'published_at':f'2026-10-21T{9+n//3:02d}:{j*10:02d}:00+09:00',
          'framing':['기회와 기대','현장의 과제','제도와 실행','지역의 시선','남은 질문'][j], 'is_demo':True})
    ready=status=='ready'
    perspectives=[{'label':'기회와 기대','text':'도입으로 얻을 수 있는 편익과 새로운 가능성을 강조합니다.','article_ids':[articles[0]['id']]},
      {'label':'현장의 과제','text':'비용 부담과 실행 과정에서 소외될 수 있는 집단을 살펴봅니다.','article_ids':[articles[1]['id']]},
      {'label':'제도와 실행','text':'단계적인 시행과 성과 검증을 위한 조건에 주목합니다.','article_ids':[articles[2]['id']]}] if ready else []
    bullets=[{'text':dek,'article_ids':[articles[0]['id'],articles[1]['id']]},
      {'text':'가상 자료에서는 기대 효과와 실행 비용을 서로 다른 쟁점으로 다룹니다.','article_ids':[articles[0]['id'],articles[2]['id']]},
      {'text':'구체적인 효과는 후속 자료와 당사자 의견을 확인해야 합니다.','article_ids':[articles[1]['id']]}] if ready else []
    stories.append({'id':sid,'title':title,'category':category,'dek':dek,
      'updated_at':f'2026-10-21T{13-n//3:02d}:{50-n%3*15:02d}:00+09:00',
      'keywords':tags,'visual':visual,'coverage':{'publisher_count':len(set(a['publisher_id'] for a in articles)),
      'article_count':len(articles),'perspective_count':len(perspectives),'label_status':'demo'},
      'summary':{'status':status,'bullets':bullets,'unknowns':['실제 보도가 아닌 UI 개발용 가상 자료입니다.'],
        'model_version':'fixture-only' if ready else None,'prompt_version':'demo-v1' if ready else None},
      'perspectives':perspectives,'articles':articles,'public_interest':interest,'is_demo':True})
data={'dataset_version':'demo-2026-10-21-v1','generated_at':'2026-10-21T14:00:00+09:00','stories':stories}
(ROOT/'contracts/fixtures.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
analyst_text='수집과 요약 및 게시가 허용된 본문을 여기에 전달합니다.'
batch={'schema_version':'1.0','batch_id':'demo-batch-001','articles':[{
 'id':'article-demo-001','canonical_url':'https://example.com/demo/input-001','publisher_id':'p-01',
 'publisher_group_id':'g-01','title':'가상 뉴스 데이터 전달 예시','text':analyst_text,
 'published_at':'2026-10-21T09:00:00+09:00','collected_at':'2026-10-21T09:10:00+09:00',
 'category':'technology','content_hash':sha256(analyst_text.encode('utf-8')).hexdigest(),'license_status':'allowed',
 'allowed_uses':['collect','store','summarize','publish_summary']}]}
(ROOT/'contracts/analyst-batch.example.json').write_text(json.dumps(batch,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Wrote {len(stories)} fictional stories')
