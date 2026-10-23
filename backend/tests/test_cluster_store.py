"""Private batch persistence preserves original articles and never publishes candidates."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout, redirect_stderr

from backend.tests.test_cluster_preview import bundle, save


def fixture(folder, *, allowed=True):
    exported, articles = bundle(folder)
    rights = dict(collect='allowed' if allowed else 'unknown',
                  store='allowed' if allowed else 'unknown', display_image='unknown')
    exported['groups'][0]['representative']['metadata'] = {'rights':rights,'is_demo':True}
    save(folder, exported, articles)
    (folder/'input.json').write_text(json.dumps({'articles':[
        {**row, 'rights':rights, 'is_demo':True} for row in articles]}), encoding='utf-8')
    return exported, articles


def configured_schema(connection):
    from backend.app.cluster_store.repository import SCHEMA_MARKER,COLUMNS,TABLES
    fallback=connection.execute.return_value
    def execute(statement,*args,**kwargs):
        sql=str(statement);result=MagicMock()
        if 'SELECT obj_description' in sql:
            result.scalar_one_or_none.return_value=SCHEMA_MARKER
        elif 'FROM information_schema.columns' in sql:
            result.mappings.return_value.all.return_value=[dict(table_name=t,column_name=c) for t,cols in COLUMNS.items() for c in cols]
        elif 'FROM pg_catalog.pg_class c JOIN' in sql:
            result.mappings.return_value.all.return_value=[dict(relname=t,relkind='r',relrowsecurity=True,exposed=False) for t in TABLES]
        else:return fallback
        return result
    connection.execute.side_effect=execute
    return execute


class ClusterStoreBundleTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.cluster_store'),
                             'Missing explicit private clustering storage boundary')
        return importlib.import_module('backend.app.cluster_store')

    def test_original_body_ids_urls_and_representative_survive(self):
        api = self.api()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            exported, original = fixture(folder)
            before = {p.name:p.read_bytes() for p in folder.iterdir()}
            value = api.prepare_bundle(folder, namespace='unit-fixture')
            self.assertEqual(value['schema_version'], 'prism-cluster-storage/v1')
            payload = value['payload']
            self.assertEqual(payload['namespace'], 'unit-fixture')
            self.assertFalse(payload['automatic_publication'])
            self.assertFalse(payload['accuracy_measured'])
            self.assertTrue(payload['requires_human_review'])
            self.assertEqual(len(payload['articles']), 2)
            by_id = {r['article_id']:r for r in payload['articles']}
            for row in original:
                stored = by_id[row['article_id']]
                for field in ('title','body','url','content_hash','publisher'):
                    self.assertEqual(stored[field], row[field])
                self.assertEqual(stored['body_sha256'], sha256(row['body'].encode()).hexdigest())
            group = payload['groups'][0]
            self.assertEqual(group['representative_article_id'], exported['groups'][0]['representative']['article_id'])
            self.assertFalse(group['same_event_verified'])
            self.assertEqual(set(group['article_ids']), {'a','b'})
            self.assertEqual(before, {p.name:p.read_bytes() for p in folder.iterdir()})
            self.assertEqual(api.validate_bundle(value), value)
            self.assertEqual(api.prepare_bundle(folder, namespace='unit-fixture'), value)
            self.assertEqual(api.summarize_bundle(value)['blocked_articles'], 0)

    def test_unknown_rights_are_preserved_and_block_writes_before_engine_use(self):
        api = self.api()
        with TemporaryDirectory() as directory:
            fixture(Path(directory), allowed=False)
            value = api.prepare_bundle(directory, namespace='unknown-rights')
            self.assertEqual(api.summarize_bundle(value)['blocked_articles'], 2)
            self.assertTrue(all(a['rights']['store']=='unknown' for a in value['payload']['articles']))
            engine = MagicMock()
            with self.assertRaises(ValueError):
                api.store_bundle(value, engine=engine)
            engine.begin.assert_not_called()
            engine.connect.assert_not_called()

    def test_explicit_denial_overrides_allowed_source_and_bad_metadata_is_rejected(self):
        api = self.api()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            exported, articles = fixture(folder)
            exported['groups'][0]['representative']['metadata']['rights']['store'] = 'denied'
            save(folder, exported, articles)
            value = api.prepare_bundle(folder, namespace='denial')
            self.assertEqual(api.summarize_bundle(value)['blocked_articles'], 1)
            self.assertEqual(next(r for r in value['payload']['articles'] if r['article_id']=='b')['rights']['store'], 'denied')
            raw = json.loads((folder/'input.json').read_text())
            raw['articles'][0]['url'] = 'https://example.org/wrong'
            (folder/'input.json').write_text(json.dumps(raw), encoding='utf-8')
            with self.assertRaises(ValueError):
                api.prepare_bundle(folder, namespace='bad-source')

    def test_corrupted_hashes_memberships_flags_and_types_are_rejected(self):
        api = self.api()
        with TemporaryDirectory() as directory:
            fixture(Path(directory))
            original = api.prepare_bundle(directory, namespace='validation')
            mutations = [
                lambda v:v.update(payload_sha256='0'*64),
                lambda v:v.update(batch_id='prism-batch-'+'0'*64),
                lambda v:v['payload']['articles'][0].update(body='changed'),
                lambda v:v['payload']['groups'][0].update(representative_article_id='missing'),
                lambda v:v['payload']['groups'][0].update(article_ids=['a','a']),
                lambda v:v['payload'].update(automatic_publication=True),
                lambda v:v['payload'].update(automatic_publication=0),
                lambda v:v['payload'].update(accuracy_measured=True),
                lambda v:v['payload']['groups'][0].update(same_event_verified=True),
                lambda v:v['payload']['articles'][0].update(image_url='http://localhost/photo.jpg'),
            ]
            for mutation in mutations:
                value=deepcopy(original)
                mutation(value)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    api.validate_bundle(value)

    def test_image_manifest_is_strictly_bound_to_original_input(self):
        api = self.api()
        from backend.app.article_images.collection import write_manifest
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'run';folder.mkdir()
            _,articles=fixture(folder)
            h=lambda name:sha256((folder/name).read_bytes()).hexdigest()
            manifest=dict(schema_version='local-news-images/v1',created_at='2026-10-23T01:00:00+00:00',
                articles_sha256=h('articles.json'),representatives_sha256=h('representatives.json'),input_sha256=h('input.json'),
                automatic_publication=False,local_preview=True,image_bytes_downloaded=0,
                summary=dict(selected_articles=2,images_found=2,statuses={'found':2}),
                results=[dict(article_id=r['article_id'],article_url=r['url'],content_hash=r['content_hash'],
                    status='found',image_url='https://example.org/'+r['article_id']+'.jpg',origin='rss_media',
                    rights_status='unknown',html_sha256=None) for r in articles])
            path=root/'images.json'
            write_manifest(manifest,path,folder)
            value=api.prepare_bundle(folder,namespace='photos',image_manifest=path)
            self.assertEqual({a['image_url'] for a in value['payload']['articles']},
                {'https://example.org/a.jpg','https://example.org/b.jpg'})
            raw=json.loads((folder/'input.json').read_text(encoding='utf-8'))
            raw['articles'][0]['rights']['display_image']='denied'
            (folder/'input.json').write_text(json.dumps(raw),encoding='utf-8')
            with self.assertRaises(ValueError):
                api.prepare_bundle(folder,namespace='stale-photos',image_manifest=path)

    def test_output_is_exclusive_and_invalid_namespace_or_source_fails(self):
        api = self.api()
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'run';folder.mkdir()
            fixture(folder)
            value=api.prepare_bundle(folder,namespace='fresh')
            target=root/'batch.json'
            api.write_bundle(value,target)
            self.assertEqual(api.validate_bundle(json.loads(target.read_text(encoding='utf-8'))),value)
            before=target.read_bytes()
            with self.assertRaises(FileExistsError):api.write_bundle(value,target)
            self.assertEqual(target.read_bytes(),before)
            for namespace in ('',' ','../escape','x'*81):
                with self.subTest(namespace=namespace),self.assertRaises(ValueError):
                    api.prepare_bundle(folder,namespace=namespace)
            (folder/'articles.json').write_text('{"articles":[],"articles":[]}',encoding='utf-8')
            with self.assertRaises(ValueError):api.prepare_bundle(folder,namespace='corrupt')

    def test_schema_is_additive_private_and_stores_source_text_and_image_url(self):
        self.api()
        path=Path(__file__).resolve().parents[2]/'database/migrations/20261023_001_cluster_storage.sql'
        self.assertTrue(path.is_file())
        sql=path.read_text().lower()
        for name in ('prism_cluster_batches','prism_cluster_articles','prism_cluster_groups','prism_cluster_members'):
            self.assertIn('create table private.'+name,sql)
            self.assertIn('alter table private.'+name+' enable row level security',sql)
        self.assertIn('raw_text text',sql)
        self.assertIn('image_url text',sql)
        self.assertNotIn('alter table public.',sql)
        self.assertNotIn('drop ',sql)
        self.assertNotIn('truncate ',sql)
        self.assertNotIn('news_v2_',sql)

    def test_store_commits_one_private_batch_and_failure_uses_the_transaction_context(self):
        api=self.api()
        with TemporaryDirectory() as directory:
            fixture(Path(directory))
            value=api.prepare_bundle(directory,namespace='transaction-test')
            engine=MagicMock();connection=engine.begin.return_value.__enter__.return_value
            configured_schema(connection)
            connection.execute.return_value.scalar_one_or_none.return_value=value['batch_id']
            result=api.store_bundle(value,engine=engine)
            self.assertEqual(result['status'],'stored')
            sqls=[str(call.args[0]) for call in connection.execute.call_args_list]
            inserts=[sql for sql in sqls if sql.startswith('INSERT')]
            self.assertEqual(len(inserts),6)
            self.assertTrue(all('private.prism_cluster_' in sql for sql in inserts))
            self.assertTrue(all('public.' not in sql and 'news_v2_' not in sql and
                not sql.lstrip().upper().startswith(('UPDATE ','DELETE ','ALTER ','TRUNCATE ')) for sql in sqls))
            engine.begin.assert_called_once()
            engine=MagicMock();connection=engine.begin.return_value.__enter__.return_value
            schema_execute=configured_schema(connection)
            def execute(statement,*args,**kwargs):
                if 'INSERT INTO private.prism_cluster_articles' in str(statement):
                    raise RuntimeError('synthetic child failure')
                if str(statement).startswith('SELECT'):
                    return schema_execute(statement,*args,**kwargs)
                response=MagicMock();response.scalar_one_or_none.return_value=value['batch_id']
                return response
            connection.execute.side_effect=execute
            with self.assertRaises(RuntimeError):api.store_bundle(value,engine=engine)
            self.assertIs(engine.begin.return_value.__exit__.call_args.args[0],RuntimeError)

    def test_existing_batch_is_idempotent_and_conflicts_fail_without_child_writes(self):
        api=self.api()
        with TemporaryDirectory() as directory:
            fixture(Path(directory))
            value=api.prepare_bundle(directory,namespace='retry')
            for mismatch in (False,True):
                engine=MagicMock();connection=engine.begin.return_value.__enter__.return_value
                configured_schema(connection)
                connection.execute.return_value.scalar_one_or_none.return_value=None
                connection.execute.return_value.mappings.return_value.first.return_value=dict(
                    payload_sha256='0'*64 if mismatch else value['payload_sha256'],article_count=2,group_count=1)
                if mismatch:
                    with self.assertRaises(ValueError):api.store_bundle(value,engine=engine)
                else:
                    self.assertEqual(api.store_bundle(value,engine=engine)['status'],'already_stored')
                self.assertFalse(any('INSERT INTO private.prism_cluster_articles' in str(c.args[0])
                                     for c in connection.execute.call_args_list))

    def test_cli_prepares_offline_defaults_to_plan_and_sanitizes_failures(self):
        self.api()
        self.assertIsNotNone(importlib.util.find_spec('backend.app.cluster_store.__main__'), 'Missing explicit storage CLI')
        cli=importlib.import_module('backend.app.cluster_store.__main__')
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'run';folder.mkdir();fixture(folder)
            target=root/'batch.json';out=io.StringIO()
            with redirect_stdout(out),patch('backend.app.cluster_store.repository._engine') as get_engine:
                self.assertEqual(cli.main(['prepare','--results-dir',str(folder),'--namespace','cli','--output',str(target)]),0)
            get_engine.assert_not_called()
            self.assertTrue(target.is_file())
            with redirect_stdout(io.StringIO()),patch('backend.app.cluster_store.__main__.plan_bundle',return_value={'status':'ready'}) as plan,patch('backend.app.cluster_store.__main__.store_bundle') as store:
                self.assertEqual(cli.main(['store','--batch',str(target)]),0)
            plan.assert_called_once();store.assert_not_called()
            error=io.StringIO()
            with redirect_stderr(error),patch('backend.app.cluster_store.__main__.plan_bundle',side_effect=RuntimeError('password-do-not-log')):
                self.assertNotEqual(cli.main(['plan','--batch',str(target)]),0)
            self.assertNotIn('password-do-not-log',error.getvalue())
            self.assertNotIn('본문',out.getvalue())

    def test_legacy_allowed_uses_cannot_be_a_string_object_or_boolean(self):
        api=self.api()
        with TemporaryDirectory() as directory:
            folder=Path(directory)
            for invalid in ('collect,store',{'collect':True,'store':True},True,['collect',True]):
                exported,articles=fixture(folder)
                exported['groups'][0]['representative']['metadata']={
                    'license_status':'allowed','allowed_uses':invalid}
                save(folder,exported,articles)
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                    api.prepare_bundle(folder,namespace='invalid-permission-type')

    def test_same_names_with_wrong_schema_marker_are_not_accepted(self):
        self.api()
        from backend.app.cluster_store.repository import schema_status,TABLES
        engine=MagicMock();connection=engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.scalars.return_value.all.return_value=list(TABLES)
        connection.execute.return_value.scalar_one_or_none.return_value='another application table'
        with self.assertRaises(ValueError):schema_status(engine=engine)

    def test_write_rejects_a_foreign_table_marker_before_any_insert(self):
        api=self.api()
        with TemporaryDirectory() as directory:
            fixture(Path(directory));value=api.prepare_bundle(directory,namespace='foreign-table')
            engine=MagicMock();connection=engine.begin.return_value.__enter__.return_value
            connection.execute.return_value.scalar_one_or_none.return_value='another application table'
            with self.assertRaises(ValueError):api.store_bundle(value,engine=engine)
            self.assertFalse(any(str(c.args[0]).startswith('INSERT') for c in connection.execute.call_args_list))

    def test_envelope_limit_covers_the_file_that_prepare_will_write(self):
        api=self.api()
        module=importlib.import_module('backend.app.cluster_store.bundle')
        with TemporaryDirectory() as directory:
            fixture(Path(directory));value=api.prepare_bundle(directory,namespace='envelope-limit')
            limit=len(module.canonical(value['payload']).encode())+20
            self.assertGreater(len(module.canonical(value).encode())+1,limit)
            with patch.object(module,'MAX_BYTES',limit),self.assertRaises(ValueError):
                api.validate_bundle(value)


if __name__=='__main__':unittest.main()
