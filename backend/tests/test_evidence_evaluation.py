import json
from pathlib import Path
import unittest
from copy import deepcopy
from backend.app.evidence.evaluation import evaluate_suite,operation_summary

class EvaluationTests(unittest.TestCase):
    def suite(self):return json.loads((Path(__file__).resolve().parents[2]/'contracts/evaluation/reading.synthetic.json').read_text(encoding='utf-8'))

    def test_guard_regression_does_not_claim_model_accuracy(self):
        result=evaluate_suite(self.suite())
        self.assertFalse(result['real_world_accuracy_measured'])
        self.assertEqual(result['passed_cases'],result['case_count'])
        broken=self.suite();broken['cases'][0]['expected_labels']=[]
        changed=evaluate_suite(broken)
        self.assertEqual(changed['fp'],1)
        self.assertLess(changed['passed_cases'],changed['case_count'])

    def test_duplicate_cases_and_unmarked_dataset_rejected(self):
        suite=self.suite();suite['cases'].append(deepcopy(suite['cases'][0]))
        with self.assertRaises(ValueError):evaluate_suite(suite)
        suite=self.suite();suite['provenance']='human'
        with self.assertRaises(ValueError):evaluate_suite(suite)

    def test_unknown_cost_and_empty_records_do_not_become_zero_success(self):
        empty=operation_summary([])
        self.assertIsNone(empty['error_rate']);self.assertIsNone(empty['known_estimated_cost_usd'])
        records=[{'status':'ok','elapsed_ms':100,'estimated_cost_usd':None},{'status':'error','elapsed_ms':900,'estimated_cost_usd':.01}]
        result=operation_summary(records)
        self.assertEqual(result['latency_ms']['all']['p95'],900)
        self.assertEqual(result['latency_ms']['success']['p95'],100)
        self.assertEqual(result['cost_coverage'],.5)
        self.assertEqual(result['error_rate'],.5)
        with self.assertRaises(ValueError):operation_summary([{'status':'ok','elapsed_ms':-1}])
