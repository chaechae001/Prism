"""Serial periodic worker. Ingest commit precedes model input readback."""
from collections import Counter
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Event
from uuid import uuid4

from ..cluster_store.bundle import canonical,prepare_bundle,write_bundle
from ..article_images.collection import write_manifest
from .collection import collect_rows
from .repository import Repository,stable_row


def _model_identity(model_dir):
    files={}
    for name in ('tokenizer.json','onnx/model_quantized.onnx'):
        digest=sha256()
        with (model_dir/name).open('rb') as stream:
            for chunk in iter(lambda:stream.read(1_048_576),b''):digest.update(chunk)
        files[name]=digest.hexdigest()
    return files


def _input_hash(rows,settings,*,model_identity=None):
    return sha256(canonical(dict(articles=[stable_row(r) for r in rows],
        profile=settings.profile,analysis_revision=settings.analysis_revision,
        model=model_identity if model_identity is not None else _model_identity(settings.model_dir))).encode()).hexdigest()


def _images(rows,folder,output):
    digest=lambda name:sha256((folder/name).read_bytes()).hexdigest()
    results=[]
    for row in rows:
        found=bool(row.get('image_url')) and row['rights']['display_image']!='denied'
        results.append(dict(article_id=row['article_id'],article_url=row['url'],content_hash=row['content_hash'],
            status='found' if found else 'missing',image_url=row.get('image_url') if found else None,
            origin=row.get('image_origin') or 'og_image' if found else None,
            rights_status=row['rights']['display_image'],html_sha256=row.get('html_sha256')))
    value=dict(schema_version='local-news-images/v1',created_at=max(r['published_at'] for r in rows),
        articles_sha256=digest('articles.json'),representatives_sha256=digest('representatives.json'),
        input_sha256=digest('input.json'),automatic_publication=False,local_preview=True,image_bytes_downloaded=0,
        summary=dict(selected_articles=len(results),images_found=sum(r['status']=='found' for r in results),
            statuses=dict(Counter(r['status'] for r in results))),results=results)
    write_manifest(value,output,folder)


def run_cycle(settings,*,engine=None,repository=None,collector=None,analyzer=None,encoder=None,now=None):
    base=dict(namespace=settings.namespace,llm_calls=0,automatic_publication=False,usage_scope='local_test')
    if not settings.active_sources:return dict(**base,status='waiting_for_sources',articles=0,groups=0)
    custom_analyzer=analyzer is not None
    if analyzer is None:
        if encoder is None and not settings.check()['local_model_ready']:
            raise FileNotFoundError('Configure existing local E5 tokenizer/model files; downloads are disabled')
        from ..clustering.adapter import run_batch
        analyzer=run_batch
    if encoder is not None and not hasattr(encoder,'model_dir'):
        model_identity=dict(provided_encoder=encoder.model_id)
    elif custom_analyzer:
        model_identity=dict(provided_analyzer=analyzer.__module__+'.'+analyzer.__qualname__)
    else:model_identity=_model_identity(settings.model_dir)
    repository=repository if repository is not None else Repository(engine)
    cutoff=now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:raise ValueError('Worker cutoff must have timezone')
    with repository.lock(settings.namespace) as acquired:
        if not acquired:return dict(**base,status='already_running',articles=0,groups=0)
        known=repository.known_ids(settings.namespace,since=cutoff-timedelta(seconds=settings.refetch_seconds))
        observations=repository.observations(settings.namespace,after=cutoff-timedelta(hours=settings.window_hours))
        collected=(collector or collect_rows)(settings,known_ids=known,observations=observations,cutoff=cutoff)
        observed=repository.ingest(settings.namespace,collected['articles'],observed_at=cutoff)
        # Preserve valid source rows, but never advance preview after a failed or
        # truncated feed. Excluding committed IDs lets a backlog drain next cycle.
        if collected.get('complete') is False:
            return dict(**base,status='collection_incomplete',observed_articles=observed,
                        collection=collected['summary'],articles=0,groups=0)
        rows=repository.read_window(settings.namespace,after=cutoff-timedelta(hours=settings.window_hours),
                                   before=cutoff,maximum=settings.max_articles)
        # Apply the current source policy conservatively to read-back rows. A
        # saved denial/unknown cannot be promoted by editing the worker config.
        policies={s.key+'-economy':s for s in settings.active_sources}
        eligible=[]
        for row in rows:
            policy=policies.get(row['source_id'])
            if policy is None:continue
            for use,state in policy.rights.items():
                prior=row['rights'][use]
                row['rights'][use]='denied' if 'denied' in (prior,state) else 'allowed' if prior==state=='allowed' else 'unknown'
            if row['rights']['display_image']=='denied':row.update(image_url=None,image_origin=None)
            if all(row['rights'][use]=='allowed' for use in ('collect','store')):eligible.append(row)
        rows=eligible
        if not rows:return dict(**base,status='no_eligible_articles',observed_articles=observed,articles=0,groups=0)
        hashed=_input_hash(rows,settings,model_identity=model_identity)
        if hashed==repository.latest_input_hash(settings.namespace):
            return dict(**base,status='unchanged',observed_articles=observed,articles=len(rows),groups=None)
        settings.work_dir.mkdir(parents=True,exist_ok=True)
        cycle_dir=settings.work_dir/('cycle-'+cutoff.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:10])
        cycle_dir.mkdir()
        output=cycle_dir/'analysis'
        result=analyzer(rows,output,input_format='collector',profile=settings.profile,
            encoder=encoder,model_dir=settings.model_dir,cache_path=settings.work_dir/'e5.sqlite3',
            provenance=dict(mode='scheduled_db_readback',namespace=settings.namespace,input_sha256=hashed))
        if result['article_count']!=len(rows) or not result['group_count']:
            raise ValueError('Analysis did not preserve the complete DB input')
        image_path=cycle_dir/'images.json'
        _images(rows,output,image_path)
        bundle=prepare_bundle(output,namespace=settings.namespace,image_manifest=image_path)
        write_bundle(bundle,cycle_dir/'batch.json')
        stored=repository.store(bundle,input_hash=hashed,analyzed_at=cutoff)
        return dict(**base,status='completed',observed_articles=observed,articles=result['article_count'],
            groups=result['group_count'],batch_id=bundle['batch_id'],storage_status=stored['status'],collection=collected['summary'])


def _status(settings,value):
    settings.work_dir.mkdir(parents=True,exist_ok=True)
    target=settings.work_dir/'status.json';temporary=settings.work_dir/('status-'+uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
    os.replace(temporary,target)


def run_forever(settings,*,stop=None,cycle=None,emit=None):
    stop=stop if stop is not None else Event()
    while not stop.is_set():
        try:
            value=(cycle or run_cycle)(settings)
        except Exception as exc:
            value=dict(namespace=settings.namespace,status='failed',error_type=type(exc).__name__,llm_calls=0)
        value.update(checked_at=datetime.now(timezone.utc).isoformat(),interval_seconds=settings.interval_seconds)
        _status(settings,value)
        if emit:emit(value)
        # Wait after completion, not on overlapping wall-clock ticks. Event.wait
        # handles termination without a busy retry loop after failure.
        if stop.wait(settings.interval_seconds):break
