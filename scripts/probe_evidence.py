"""Explicit real API/image smoke evaluation. Never run billable probes in CI."""
import argparse
import asyncio
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

async def probe(args):
    from backend.app.config import load_environment
    load_environment()
    # Probe output is private; never write to the operational DB as a side effect.
    os.environ['PRISM_LLM_METRICS_ENABLED']='0'
    result={'scope':'explicit_official_api_and_synthetic_image_smoke','real_news_quality_measured':False,'public_data':[],'vision':[]}
    if args.official_data:
        from backend.app.evidence.public_data import fetch
        for indicator in ('kosis_cpi','inflation','population','gdp'):
            try:result['public_data'].append({'success':True,**(await fetch(indicator)).model_dump()})
            except Exception as exc:result['public_data'].append({'success':False,'indicator':indicator,'error_type':type(exc).__name__})
    if args.vision:
        if not args.confirm_external:raise ValueError('유료·외부 전송 가능한 비전 실험은 --confirm-external이 필요합니다.')
        from PIL import Image,ImageDraw
        from backend.app.evidence.vision import analyze,VisionInput
        from backend.app.ai_pipeline.telemetry import current
        for expected in ('PRISM 42','2020=100','119.77 120.43',''):
            image=Image.new('RGB',(500,160),'white')
            if expected:ImageDraw.Draw(image).text((25,55),expected,fill='black',font_size=36)
            stream=BytesIO();image.save(stream,format='PNG');usage={};token=current.set(usage);start=perf_counter()
            try:
                response=await analyze('synthetic-vision-evaluation',VisionInput(image_base64=base64.b64encode(stream.getvalue()).decode(),media_type='image/png',consent_external=True))
                actual=' '.join(response.output.visible_text)
                match=''.join(expected.split()).casefold()==''.join(actual.split()).casefold()
                result['vision'].append({'status':'ok','expected_text':expected,'actual_text':actual,'text_exact_match':match,
                    'elapsed_ms':round((perf_counter()-start)*1000),'estimated_cost_usd':None,'model':response.model,
                    'limitations_present':bool(response.output.limitations),**usage})
            except Exception as exc:result['vision'].append({'status':'error','error_type':type(exc).__name__,'elapsed_ms':round((perf_counter()-start)*1000),'estimated_cost_usd':None})
            finally:current.reset(token)
        from backend.app.evidence.evaluation import operation_summary
        result['vision_operations']=operation_summary(result['vision'])
        result['vision_text_exact_match']={'passed':sum(r.get('text_exact_match',False) for r in result['vision']),'total':len(result['vision'])}
    result['notice']='이미지 텍스트 smoke 표본 4개입니다. 실기사 이미지 설명의 정확도·개인정보 안전성·방어율이나 일반화 성능이 아닙니다. 비용 미상은 무료라는 뜻이 아닙니다.'
    return result

def main():
    parser=argparse.ArgumentParser(description='공식 API·합성 이미지의 명시적 실호출 검증')
    parser.add_argument('--official-data',action='store_true');parser.add_argument('--vision',action='store_true')
    parser.add_argument('--confirm-external',action='store_true');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not (args.official_data or args.vision):parser.error('실행할 검증을 명시해주세요.')
    try:
        result=asyncio.run(probe(args));args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'official_api_success':sum(r['success'] for r in result['public_data']),
            'official_api_total':len(result['public_data']),'vision_text_exact_match':result.get('vision_text_exact_match'),
            'vision_operations':result.get('vision_operations')},ensure_ascii=False))
        return int(any(not r['success'] for r in result['public_data']) or any(r['status']=='error' for r in result['vision']))
    except (ValueError,OSError):
        print('입력·출력 경로와 명시적 외부 실험 동의를 확인해주세요.');return 1

if __name__=='__main__':raise SystemExit(main())
