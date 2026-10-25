import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from backend.app.connected_news import main
from backend.app.connection_repository import Snapshot
from backend.app.repository import FixtureRepository


class ConnectedNewsCheckTests(unittest.TestCase):
    def test_readiness_reports_counts_without_provider_call_or_secrets(self):
        story = FixtureRepository().all()[0]
        data = Snapshot([story],'test',False,'cluster-db')
        output = io.StringIO()
        with patch.dict(os.environ,{},clear=False), \
                patch('backend.app.connection_repository.load_snapshot',return_value=data), \
                patch('backend.app.services.cluster_context.chat_cluster_bodies',return_value=[{'article_id':story.articles[0].id,'text':'PRIVATE BODY','is_excerpt':False}]), \
                patch('backend.app.chat.providers.settings',return_value=('elice','PRIVATE KEY','test-model','https://example.org')), \
                redirect_stdout(output):
            result = main([])
        self.assertEqual(result,0)
        report = json.loads(output.getvalue())
        self.assertTrue(report['ready'])
        self.assertEqual(report['llm_calls'],0)
        self.assertEqual(report['database_writes'],0)
        self.assertNotIn('PRIVATE',output.getvalue())

    def test_readiness_failure_does_not_print_database_exception_details(self):
        output = io.StringIO()
        with patch.dict(os.environ,{},clear=False), \
                patch('backend.app.connection_repository.load_snapshot',side_effect=RuntimeError('password=PRIVATE')), \
                redirect_stdout(output):
            self.assertEqual(main([]),1)
        self.assertFalse(json.loads(output.getvalue())['ready'])
        self.assertNotIn('PRIVATE',output.getvalue())
