"""Image metadata collection is explicit; feed reads stay offline and optional."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.tests.test_cluster_preview import bundle


ARTICLE_URL = 'https://news.sbs.co.kr/news/endPage.do?news_id=N1008810165'
IMAGE_URL = 'https://img.sbs.co.kr/news/2026/10/22/article.jpg'


class ArticleImageTests(unittest.TestCase):
    def media(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.article_images'))
        return importlib.import_module('backend.app.article_images')

    def page(self, image=IMAGE_URL, news_id='N1008810165'):
        return f'''<html><head><link rel="canonical" href="https://news.sbs.co.kr/news/endPage.do?news_id={news_id}">
        <meta property="og:title" content="원문 제목"><meta property="og:image" content="{image}"></head>
        <body><div class="text_area">{'기사 본문입니다. ' * 30}</div></body></html>'''

    def input(self, folder):
        exported, articles = bundle(folder)
        for i, article in enumerate(articles):
            article['url'] = ARTICLE_URL.replace('N1008810165', f'N100881016{i+5}')
            article['publisher'] = 'SBS'
        exported['groups'][0]['representative'].update(articles[1])
        exported['groups'][0]['related_articles'] = [articles[0]]
        from backend.tests.test_cluster_preview import save
        save(folder, exported, articles)
        return articles

    def test_rss_uses_image_media_and_skips_video_audio_and_unsafe_candidates(self):
        media = self.media()
        rows = [dict(kind='enclosure',type='audio/mpeg',url='https://cdn.example.org/audio.mp3'),
                dict(kind='media:content',medium='video',url='https://cdn.example.org/movie.mp4'),
                dict(kind='media:thumbnail',url='http://127.0.0.1/private.jpg'),
                dict(kind='{http://search.yahoo.com/mrss/}thumbnail',url='//img.sbs.co.kr/news/thumb.jpg')]
        result = media.image_from_rss(rows, ARTICLE_URL)
        self.assertEqual(result, {'url':'https://img.sbs.co.kr/news/thumb.jpg','origin':'rss_media'})

    def test_html_prefers_open_graph_resolves_relative_urls_and_ignores_unrelated_images(self):
        media = self.media()
        html = '<img src="https://ads.example.org/ad.jpg"><meta name="twitter:image" content="https://img.example.org/twitter.jpg"><meta property="og:image" content="/article.jpg?a=1&amp;b=2">'
        self.assertEqual(media.image_from_html(html, ARTICLE_URL),
                         {'url':'https://news.sbs.co.kr/article.jpg?a=1&b=2','origin':'og_image'})
        self.assertIsNone(media.image_from_html('<img src="https://ads.example.org/ad.jpg">', ARTICLE_URL))

    def test_unsafe_image_urls_and_obvious_logo_placeholders_are_not_used(self):
        media = self.media()
        values = ['javascript:alert(1)','data:image/png;base64,AAAA','file:///image.jpg',
                  'https://user:secret@img.example.org/a.jpg','http://localhost/a.jpg',
                  'http://10.0.0.1/a.jpg','http://[::1]/a.jpg','https://internal.local/a.jpg',
                  'https://img.example.org:8443/a.jpg','https://img.example.org/logo.jpg',
                  'https://img.example.org/default_og.png']
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(media.safe_image_url(value))
        self.assertEqual(media.safe_image_url(IMAGE_URL), IMAGE_URL)

    def test_image_query_parameters_are_not_html_decoded_twice(self):
        media=self.media()
        url=IMAGE_URL+'?width=600&copy=1'
        self.assertEqual(media.safe_image_url(url),url)
        html=f'<meta property="og:image" content="{IMAGE_URL}?width=600&amp;copy=1">'
        self.assertEqual(media.image_from_html(html,ARTICLE_URL)['url'],url)

    def test_malformed_rss_url_is_skipped_in_favor_of_the_next_image(self):
        media=self.media()
        rows=[dict(kind='media:thumbnail',url='http://[::1/a.jpg'),
              dict(kind='media:thumbnail',url=IMAGE_URL)]
        self.assertEqual(media.image_from_rss(rows,ARTICLE_URL)['url'],IMAGE_URL)

    def test_native_original_metadata_preserves_rss_images_and_denied_rights(self):
        media=self.media()
        for placement in ('input', 'representative'):
            with self.subTest(placement=placement), TemporaryDirectory() as directory:
                folder=Path(directory)
                articles=self.input(folder)
                original=deepcopy(articles)
                exported=json.loads((folder/'representatives.json').read_text(encoding='utf-8'))
                if placement=='input':
                    original[0]['media']=[dict(kind='media:thumbnail',url=IMAGE_URL)]
                    exported['groups'][0]['representative']['metadata']={'rights_snapshot':{'display_image':'denied'}}
                else:
                    original[0]['rights']={'display_image':'denied'}
                    exported['groups'][0]['representative']['metadata']={'media':[dict(kind='media:thumbnail',url=IMAGE_URL)]}
                (folder/'input.json').write_text(json.dumps({'articles':original}),encoding='utf-8')
                (folder/'representatives.json').write_text(json.dumps(exported),encoding='utf-8')
                client=Mock(requests_made=0)
                result=media.collect_images(folder,client=client)
                client.get.assert_not_called()
                self.assertEqual({r['status'] for r in result['results']},{'found','rights_denied'})
                found=next(r for r in result['results'] if r['status']=='found')
                self.assertEqual(found['origin'],'rss_media')
                self.assertEqual(found['image_url'],IMAGE_URL)

    def test_optional_deep_manifest_falls_back_without_losing_articles(self):
        self.media()
        from backend.app.cluster_preview import load_cluster_preview
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'results';folder.mkdir()
            self.input(folder)
            path=root/'deep.json'
            path.write_text('['*15000+'0'+']'*15000,encoding='utf-8')
            stories,version,notes=load_cluster_preview(folder,image_manifest=path)
            self.assertEqual(len(stories),1)
            self.assertTrue(all(a.image_url is None for a in stories[0].articles))
            self.assertTrue(any('이미지' in note and '확인' in note for note in notes))

    def test_changed_original_rss_metadata_invalidates_the_optional_images(self):
        media=self.media()
        from backend.app.cluster_preview import load_cluster_preview
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'results';folder.mkdir()
            articles=self.input(folder)
            original=deepcopy(articles)
            for row in original: row['media']=[dict(kind='media:thumbnail',url=IMAGE_URL)]
            path=folder/'input.json'
            path.write_text(json.dumps({'articles':original}),encoding='utf-8')
            client=Mock(requests_made=0)
            manifest=media.collect_images(folder,client=client)
            output=root/'images.json';media.write_manifest(manifest,output,folder)
            before=load_cluster_preview(folder,image_manifest=output)
            self.assertIsNotNone(before[0][0].articles[0].image_url)
            original[0]['rights']={'display_image':'denied'}
            path.write_text(json.dumps({'articles':original}),encoding='utf-8')
            after=load_cluster_preview(folder,image_manifest=output)
            self.assertTrue(all(a.image_url is None for a in after[0][0].articles))
            self.assertNotEqual(before[1],after[1])

    def test_rss_metadata_for_a_different_article_is_rejected_before_http(self):
        media=self.media()
        with TemporaryDirectory() as directory:
            folder=Path(directory)
            articles=self.input(folder)
            original=deepcopy(articles)
            original[0]['url']=ARTICLE_URL.replace('N1008810165','N1008999999')
            original[0]['media']=[dict(kind='media:thumbnail',url=IMAGE_URL)]
            (folder/'input.json').write_text(json.dumps({'articles':original}),encoding='utf-8')
            client=Mock(requests_made=0)
            with self.assertRaises(ValueError): media.collect_images(folder,client=client)
            client.get.assert_not_called()

    def test_cli_rejects_existing_output_before_collecting_anything(self):
        self.media()
        cli=importlib.import_module('backend.app.article_images.__main__')
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'results';folder.mkdir()
            output=root/'already.json';output.write_text('{}',encoding='utf-8')
            with patch.object(cli,'collect_images') as collect, patch('sys.stderr'):
                self.assertEqual(cli.main(['--results-dir',str(folder),'--output',str(output)]),2)
            collect.assert_not_called()

    def test_article_contract_accepts_optional_image_but_rejects_unsafe_url(self):
        from backend.app.models import Article
        row = dict(id='a',publisher_id='sbs',publisher_name='SBS',title='기사',url=ARTICLE_URL,
                   published_at='2026-10-22T09:00:00+09:00',framing='대표기사',is_demo=False)
        article = Article.model_validate({**row,'image_url':IMAGE_URL})
        self.assertEqual(str(article.image_url), IMAGE_URL)
        self.assertIsNone(Article.model_validate(row).image_url)
        for value in ('javascript:alert(1)','http://127.0.0.1/a.jpg'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Article.model_validate({**row,'image_url':value})

    def test_collection_matches_article_identity_and_keeps_missing_images_optional(self):
        media = self.media()
        with TemporaryDirectory() as directory:
            folder=Path(directory)
            articles=self.input(folder)
            before={p.name:p.read_bytes() for p in folder.iterdir()}
            client=Mock(requests_made=0)
            client.get.side_effect=[SimpleNamespace(url=articles[0]['url'],status=200,
                headers={'content-type':'text/html; charset=utf-8'},body=self.page().encode()),
                SimpleNamespace(url=articles[1]['url'],status=200,
                headers={'content-type':'text/html'},body=self.page(news_id='N1008999999').encode())]
            manifest=media.collect_images(folder,client=client)
            self.assertEqual(manifest['results'][0]['image_url'],IMAGE_URL)
            self.assertEqual(manifest['results'][0]['status'],'found')
            self.assertEqual(manifest['results'][1]['status'],'identity_mismatch')
            self.assertIsNone(manifest['results'][1]['image_url'])
            self.assertFalse(manifest['automatic_publication'])
            self.assertEqual(manifest['image_bytes_downloaded'],0)
            self.assertEqual(manifest['results'][0]['rights_status'],'unknown')
            self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},before)
            self.assertEqual(client.get.call_args_list[0].args[2],('sbs','N1008810165'))

    def test_rss_image_needs_no_html_request_and_does_not_override_denied_rights(self):
        media=self.media()
        with TemporaryDirectory() as directory:
            folder=Path(directory)
            articles=self.input(folder)
            from backend.tests.test_cluster_preview import save
            exported=json.loads((folder/'representatives.json').read_text(encoding='utf-8'))
            articles[0]['media']=[dict(kind='media:thumbnail',url=IMAGE_URL)]
            articles[1]['rights']={'display_image':'denied'}
            save(folder,exported,articles)
            client=Mock(requests_made=0)
            manifest=media.collect_images(folder,client=client)
            client.get.assert_not_called()
            self.assertEqual(manifest['results'][0]['origin'],'rss_media')
            self.assertEqual(manifest['results'][1]['status'],'rights_denied')

    def test_robots_failure_becomes_image_status_and_does_not_discard_articles(self):
        media=self.media()
        from rss_fulltext_crawler.rss_crawler.network import FetchError
        with TemporaryDirectory() as directory:
            folder=Path(directory)
            self.input(folder)
            client=Mock(requests_made=0)
            client.get.side_effect=FetchError('robots_disallowed')
            manifest=media.collect_images(folder,client=client)
            self.assertEqual([r['status'] for r in manifest['results']],['robots_disallowed']*2)
            self.assertTrue(all(r['image_url'] is None for r in manifest['results']))

    def test_manifest_attaches_images_without_changing_cluster_membership_or_ids(self):
        media=self.media()
        from backend.app.cluster_preview import load_cluster_preview
        with TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/'results';folder.mkdir()
            articles=self.input(folder)
            client=Mock(requests_made=0)
            client.get.side_effect=lambda url,*a: SimpleNamespace(url=url,status=200,
                headers={'content-type':'text/html'},body=self.page(news_id=url.rsplit('=',1)[1]).encode())
            manifest=media.collect_images(folder,client=client)
            path=root/'images.json'
            media.write_manifest(manifest,path,folder)
            first=load_cluster_preview(folder)
            with patch('rss_fulltext_crawler.rss_crawler.network.CrawlClient',side_effect=AssertionError('No HTTP during feed reads')):
                second=load_cluster_preview(folder,image_manifest=path)
            self.assertEqual(first[0][0].id,second[0][0].id)
            self.assertEqual([a.id for a in first[0][0].articles],[a.id for a in second[0][0].articles])
            self.assertEqual(str(second[0][0].articles[0].image_url),IMAGE_URL)
            self.assertNotEqual(first[1],second[1])
            self.assertTrue(any('이미지' in note for note in second[2]))
            with self.assertRaises(FileExistsError): media.write_manifest(manifest,path,folder)
            with self.assertRaises(ValueError): media.write_manifest(manifest,folder/'images.json',folder)
            bad=deepcopy(manifest);bad['articles_sha256']='0'*64
            path.write_text(json.dumps(bad),encoding='utf-8')
            third=load_cluster_preview(folder,image_manifest=path)
            self.assertEqual(len(third[0]),1)
            self.assertTrue(all(a.image_url is None for a in third[0][0].articles))
            self.assertTrue(any('이미지' in note and '확인' in note for note in third[2]))


if __name__=='__main__': unittest.main()
