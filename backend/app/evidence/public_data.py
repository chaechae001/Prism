"""Read-only World Bank Indicators API; no arbitrary URLs or credentials."""
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
import os
from typing import Literal
import httpx
from pydantic import BaseModel

Indicator=Literal['kosis_cpi','inflation','population','gdp']
INDICATORS={
    'inflation':('FP.CPI.TOTL.ZG','소비자물가 상승률','연간 %','국가 단위 연간 소비자물가 변동률입니다. 월간 물가나 개별 품목 가격과 직접 비교하지 않습니다.'),
    'population':('SP.POP.TOTL','총인구','명','연간 국가 인구 통계입니다. 특정 지역·연령 집단의 인구와 다릅니다.'),
    'gdp':('NY.GDP.MKTP.CD','국내총생산','현재 US$','명목 GDP의 현재 미국 달러 금액입니다. 실질 성장률이나 개인 소득과 다릅니다.')}

class Observation(BaseModel):
    period:str
    value:float

class PublicData(BaseModel):
    provider:str='World Bank Indicators API'
    indicator:Indicator
    indicator_code:str
    title:str
    country:str='대한민국 (KOR)'
    unit:str
    frequency:str='연간'
    retrieved_at:str
    source_updated_at:str|None=None
    source_url:str
    observations:list[Observation]
    notice:str

_cache={}

def normalize_kosis(value):
    if not isinstance(value,list) or not value:raise ValueError('KOSIS 통계 응답을 확인할 수 없습니다.')
    rows=[];seen=set();changed=[]
    for row in value:
        if not isinstance(row,dict) or any(row.get(k)!=v for k,v in {'ORG_ID':'101','TBL_ID':'DT_1J22003','C1':'T10','ITM_ID':'T','PRD_SE':'M'}.items()):
            raise ValueError('KOSIS 통계표·전국 분류·항목·주기가 다릅니다.')
        period=row.get('PRD_DE');raw=row.get('DT');unit=row.get('UNIT_NM','')
        if not isinstance(unit,str):raise ValueError('KOSIS 단위가 잘못되었습니다.')
        unit=unit.replace('＝','=')
        if unit!='2020=100':raise ValueError('지수 기준연도가 변경되었습니다. 통계 정의를 검토해주세요.')
        if not isinstance(period,str) or len(period)!=6 or not period.isdigit() or not 1<=int(period[4:])<=12 or period in seen:
            raise ValueError('KOSIS 통계 시점이 잘못되었습니다.')
        seen.add(period)
        if raw in (None,'','-','...','…'):continue
        if isinstance(raw,bool):raise ValueError('유효하지 않은 KOSIS 수치입니다.')
        number=float(str(raw).replace(',',''))
        if not isfinite(number) or number<0:raise ValueError('유효하지 않은 KOSIS 수치입니다.')
        rows.append(Observation(period=period[:4]+'-'+period[4:],value=number))
        if isinstance(row.get('LST_CHN_DE'),str):changed.append(row['LST_CHN_DE'])
    if not rows:raise ValueError('KOSIS 지표 관측값이 없습니다.')
    return PublicData(provider='국가데이터처 KOSIS OpenAPI',indicator='kosis_cpi',indicator_code='DT_1J22003/T/T10',
        title='전국 소비자물가지수 (총지수)',unit='2020=100',frequency='월간',
        retrieved_at=datetime.now(timezone.utc).isoformat(),source_updated_at=max(changed) if changed else None,
        source_url='https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1J22003',
        observations=sorted(rows,key=lambda r:r.period,reverse=True)[:5],
        notice='2020년을 100으로 한 전국 총지수이며 상승률(%)이 아닙니다. 개별 품목 가격·지역 간 가격 수준과 직접 비교하지 않습니다. 기사 진위를 판정하지 않으며 기사 시점과 통계 기준월을 확인하세요.')

def normalize(value,indicator):
    code,title,unit,notice=INDICATORS[indicator]
    if not isinstance(value,list) or len(value)!=2 or not isinstance(value[0],dict) or not isinstance(value[1],list):
        raise ValueError('공식 통계 응답 형식을 확인할 수 없습니다.')
    rows=[];seen=set()
    for row in value[1]:
        if not isinstance(row,dict):raise ValueError('공식 통계 관측값 형식이 잘못되었습니다.')
        if row.get('countryiso3code')!='KOR' or not isinstance(row.get('indicator'),dict) or row['indicator'].get('id')!=code:
            raise ValueError('국가·통계 지표가 요청과 다릅니다.')
        period=row.get('date');number=row.get('value')
        if not isinstance(period,str) or len(period)!=4 or not period.isdigit():raise ValueError('연간 통계 시점을 확인할 수 없습니다.')
        if period in seen:raise ValueError('통계 시점이 중복되었습니다.')
        seen.add(period)
        if number is None:continue
        if type(number) not in {int,float} or not isfinite(number):raise ValueError('유효하지 않은 통계 수치입니다.')
        rows.append(Observation(period=period,value=number))
    if not rows:raise ValueError('이 지표의 관측값이 없습니다.')
    return PublicData(indicator=indicator,indicator_code=code,title=title,unit=unit,
        retrieved_at=datetime.now(timezone.utc).isoformat(),source_updated_at=value[0].get('lastupdated'),
        source_url=f'https://data.worldbank.org/indicator/{code}?locations=KR',
        observations=sorted(rows,key=lambda r:r.period,reverse=True)[:5],
        notice=notice+' 기사 진위의 판정 근거가 아닌 별도의 배경 자료입니다. 기사 시점과 통계 기준 시점을 확인하세요.')

async def fetch(indicator:Indicator,*,transport=None):
    if indicator not in {*INDICATORS,'kosis_cpi'}:raise ValueError('지원하지 않는 통계 지표입니다.')
    if transport is None and indicator in _cache:
        at,result=_cache[indicator]
        if monotonic()-at<900:return result
    if indicator=='kosis_cpi':
        from ..config import load_environment
        load_environment();key=os.getenv('KOSIS_API_KEY')
        if not key:raise ValueError('KOSIS 서버 인증 설정이 필요합니다.')
        url='https://kosis.kr/openapi/Param/statisticsParameterData.do'
        params={'method':'getList','apiKey':key,'orgId':'101','tblId':'DT_1J22003','itmId':'T','objL1':'T10',
            'format':'json','jsonVD':'Y','prdSe':'M','newEstPrdCnt':'5'}
    else:
        code=INDICATORS[indicator][0];url=f'https://api.worldbank.org/v2/country/KOR/indicator/{code}'
        params={'format':'json','per_page':10}
    async with httpx.AsyncClient(timeout=12,follow_redirects=False,trust_env=False,transport=transport) as client:
        async with client.stream('GET',url,params=params) as response:
            response.raise_for_status();raw=bytearray()
            async for part in response.aiter_bytes():
                raw.extend(part)
                if len(raw)>256000:raise ValueError('통계 응답 크기 한도를 초과했습니다.')
    import json
    result=normalize_kosis(json.loads(raw)) if indicator=='kosis_cpi' else normalize(json.loads(raw),indicator)
    if transport is None:_cache[indicator]=(monotonic(),result)
    return result
