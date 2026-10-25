import unittest
from backend.app.services.reading_modes import checked,cache_key
from unittest.mock import patch

class ReadingTests(unittest.TestCase):
 def sample(self):return {'items':[{'label':'정책 논의','text':'기사에서 정책 논의를 다룹니다.','evidence':[{'article_id':'a','quote':'정책을 논의했습니다.'}]}],'limitations':[]}
 def test_quotes_and_article_ids_must_match_source(self):
  value=self.sample();bodies=[{'article_id':'a','text':'국회에서 정책을 논의했습니다.'}]
  checked(value,bodies,'perspectives')
  value['items'][0]['evidence'][0]['article_id']='outside'
  with self.assertRaises(ValueError):checked(value,bodies,'perspectives')
  value=self.sample();value['items'][0]['evidence'][0]['quote']='원문에 없는 발언'
  with self.assertRaises(ValueError):checked(value,bodies,'sentiment')
 def test_single_article_cannot_create_fake_competing_views(self):
  value=self.sample();value['items'].append(value['items'][0].copy())
  with self.assertRaises(ValueError):checked(value,[{'article_id':'a','text':'정책을 논의했습니다.'}],'perspectives')
 def test_cache_identity_tracks_model_mode_and_source_version(self):
  with patch('backend.app.services.reading_modes.settings',return_value=('elice','secret','model-a','url')):
   key=cache_key({'hash':'a'},'easy')
   self.assertNotEqual(key,cache_key({'hash':'b'},'easy'))
   self.assertNotEqual(key,cache_key({'hash':'a'},'five_w'))
  with patch('backend.app.services.reading_modes.settings',return_value=('ollama','local','model-a','url')):
   self.assertNotEqual(key,cache_key({'hash':'a'},'easy'))

 def test_quote_ids_resolve_to_exact_source_without_model_rewriting(self):
  from backend.app.services.reading_modes import quote_catalog,materialize
  bodies=[{'article_id':'a','text':'국회에서 정책을 논의했습니다. 다음 회의는 내일입니다.'}];catalog=quote_catalog(bodies)
  value={'items':[{'label':'무엇','text':'정책 논의','evidence':[{'article_id':'a','quote_id':'q0001'}]}],'limitations':[]}
  checked(materialize(value,catalog),bodies,'five_w')
  value['items'][0]['evidence'][0]['quote_id']='missing'
  with self.assertRaises(ValueError):materialize(value,catalog)

 def test_tone_mode_rejects_generic_summary_labels(self):
  from backend.app.services.reading_modes import ToneDraft,prompt_version
  with self.assertRaises(ValueError):ToneDraft.model_validate({'items':[{'label':'사건 요약','text':'내용','evidence':[{'article_id':'a','quote_id':'q1'}]}],'limitations':[]})
  self.assertNotEqual(prompt_version('sentiment'),prompt_version('easy'))
  value=self.sample();value['items'][0]['label']='중립적 서술';value['items'].append(value['items'][0].copy())
  self.assertEqual(len(checked(value,[{'article_id':'a','text':'정책을 논의했습니다.'}],'sentiment').items),2)

 def test_comparison_axes_require_two_article_sources(self):
  bodies=[{'article_id':'a','text':'정책을 논의했습니다.'},{'article_id':'b','text':'비용은 추가 검토합니다.'}]
  value={'items':[{'label':'정책','text':'정책','evidence':[{'article_id':'a','quote':'정책을 논의했습니다.'}]},{'label':'비용','text':'비용','evidence':[{'article_id':'b','quote':'비용은 추가 검토합니다.'}]}], 'limitations':[], 'comparison':{'relation':'comparable','common_ground':[], 'differences':[{'label':'강조 차이','text':'정책과 비용','evidence':[{'article_id':'a','quote':'정책을 논의했습니다.'}]}]}}
  with self.assertRaises(ValueError):checked(value,bodies,'perspectives')
  value['comparison']['differences'][0]['evidence'].append({'article_id':'b','quote':'비용은 추가 검토합니다.'})
  self.assertEqual(len(checked(value,bodies,'perspectives').comparison.differences),1)
  value['comparison']['relation']='different_events'
  with self.assertRaises(ValueError):checked(value,bodies,'perspectives')
