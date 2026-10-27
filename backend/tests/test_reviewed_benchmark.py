from copy import deepcopy
import unittest
from backend.app.evidence.benchmark import evaluate, template
from backend.app.evidence.security_packet import prepare_packet


def packet():
    data = template(); data['provenance'] = 'synthetic'
    review = {'reviewer_ids': ['reviewer-a', 'reviewer-b'], 'adjudicated': True}
    case = {'id': 'case-1', 'event_id': 'event-1', 'split': 'test', 'kind': 'clean',
            'input_sha256': 'a' * 64, 'review': review,
            'expected': {'answerable': True, 'relevant_chunk_ids': ['c1', 'c2'], 'allowed_article_ids': ['a1']},
            'predictions': []}
    for variant in data['variants']:
        case['predictions'].append({'variant': variant['id'], 'input_sha256': 'a' * 64,
            'model': 'synthetic-model', 'prompt_version': 'v1', 'prompt_template_id': 'pending-v1',
            'output_token_limit': 1800, 'external_processing': variant['provider'] == 'elice',
            'status': 'ok', 'elapsed_ms': 100, 'estimated_cost_usd': None,
            'retrieved_chunk_ids': ['c1'], 'cited_article_ids': ['a1'], 'abstained': False,
            'judgment': {**review, 'supported_claims': 1, 'total_claims': 2,
                         'correct_citations': 1, 'total_citations': 1,
                         'task_success': True, 'attack_succeeded': None}})
    data['cases'] = [case]
    return data


class ReviewedBenchmarkTests(unittest.TestCase):
    def test_security_packet_has_controls_coverage_and_no_invented_execution(self):
        d = prepare_packet()
        self.assertEqual(sum(c['kind'] == 'injection' for c in d['cases']), 24)
        self.assertEqual(sum(c['kind'] == 'clean' for c in d['cases']), 3)
        self.assertEqual(len({c['attack_type'] for c in d['cases']}), 9)
        self.assertTrue(all(not c['predictions'] for c in d['cases']))
        r = evaluate(d)
        self.assertEqual(r['paired_cases'], 0)
        self.assertFalse(r['real_world_accuracy_measured'])
        self.assertIsNone(r['results']['development']['local-rag']['attack_success_rate'])

    def test_empty_human_template_is_not_measured_and_zero_denominators_are_null(self):
        r = evaluate(template())
        self.assertFalse(r['real_world_accuracy_measured'])
        self.assertIsNone(r['results']['test']['local-rag']['claim_support_rate'])
        self.assertIsNone(r['all_attempt_operations']['local-rag']['error_rate'])

    def test_synthetic_recall_support_and_citations_have_distinct_denominators(self):
        r = evaluate(packet()); v = r['results']['test']['local-rag']
        self.assertEqual(v['mean_recall_at_k'], .5)
        self.assertEqual(v['claim_support_rate'], .5)
        self.assertEqual(v['citation_correct_rate'], 1)
        self.assertFalse(r['real_world_accuracy_measured'])

    def test_unreviewed_or_single_reviewer_excludes_both_variants_from_pair(self):
        for target in ('gold', 'prediction'):
            d = packet()
            value = d['cases'][0]['review'] if target == 'gold' else d['cases'][0]['predictions'][0]['judgment']
            value['reviewer_ids'] = ['one']
            r = evaluate(d)
            self.assertEqual(r['paired_cases'], 0)
            self.assertEqual(r['excluded']['incomplete_paired_case'], 1)

    def test_failure_is_in_all_attempt_latency_error_rate_not_quality(self):
        d = packet(); d['cases'][0]['predictions'][0]['status'] = 'error'
        r = evaluate(d)
        self.assertEqual(r['paired_cases'], 0)
        self.assertEqual(r['all_attempt_operations']['commercial-direct']['error_rate'], 1)

    def test_development_and_test_results_are_never_pooled(self):
        d = packet(); d['cases'][0]['split'] = 'development'; d['provenance'] = 'human'
        r = evaluate(d)
        self.assertEqual(r['results']['test']['local-rag']['paired_cases'], 0)
        self.assertEqual(r['results']['development']['local-rag']['paired_cases'], 1)
        self.assertFalse(r['real_world_accuracy_measured'])

    def test_event_and_input_leakage_rejected(self):
        for same in ('event', 'hash'):
            d = packet(); other = deepcopy(d['cases'][0]); other['id'] = 'case-2'; other['split'] = 'development'
            if same == 'event': other['input_sha256'] = 'b' * 64
            else: other['event_id'] = 'another-event'
            d['cases'].append(other)
            with self.assertRaises(ValueError): evaluate(d)

    def test_mismatched_comparison_conditions_rejected(self):
        for field, value in [('input_sha256', 'b' * 64), ('output_token_limit', 1000), ('prompt_template_id', 'other')]:
            d = packet(); d['cases'][0]['predictions'][0][field] = value
            with self.assertRaises(ValueError): evaluate(d)

    def test_duplicate_ids_predictions_and_retrieved_chunks_rejected(self):
        for target in ('case', 'prediction', 'chunk'):
            d = packet()
            if target == 'case': d['cases'] *= 2
            elif target == 'prediction': d['cases'][0]['predictions'] *= 2
            else: d['cases'][0]['predictions'][0]['retrieved_chunk_ids'] *= 2
            with self.assertRaises(ValueError): evaluate(d)

    def test_injection_success_and_clean_utility_are_separate(self):
        d = packet(); c = d['cases'][0]; c['kind'] = 'injection'
        for pred in c['predictions']: pred['judgment']['attack_succeeded'] = False
        v = evaluate(d)['results']['test']['local-rag']
        self.assertEqual(v['attack_success_rate'], 0)
        self.assertEqual(v['attack_judged_cases'], 1)
        self.assertIsNone(v['clean_task_success_rate'])

    def test_unjudged_attack_is_not_counted_as_blocked(self):
        d = packet(); d['cases'][0]['kind'] = 'injection'
        v = evaluate(d)['results']['test']['local-rag']
        self.assertEqual(v['attack_judged_cases'], 0)
        self.assertIsNone(v['attack_success_rate'])

    def test_invalid_judgment_and_nonfinite_latency_rejected(self):
        for field, value in [('supported_claims', 3), ('total_claims', -1), ('task_success', 'yes')]:
            d = packet(); d['cases'][0]['predictions'][0]['judgment'][field] = value
            with self.assertRaises(ValueError): evaluate(d)
        d = packet(); d['cases'][0]['predictions'][0]['elapsed_ms'] = float('nan')
        with self.assertRaises(ValueError): evaluate(d)

    def test_reports_do_not_export_input_answer_or_reviewer_ids(self):
        d = packet(); d['cases'][0]['predictions'][0]['answer'] = 'private answer'
        d['protocol']['unrecognized_note'] = 'private answer'
        text = str(evaluate(d))
        self.assertNotIn('private answer', text)
        self.assertNotIn('reviewer-a', text)

    def test_declared_local_route_and_actual_input_hash_are_checked(self):
        with self.assertRaises(ValueError): evaluate([])
        d = packet(); d['cases'] = [None]
        with self.assertRaises(ValueError): evaluate(d)
        d = packet(); d['cases'][0]['predictions'] = [None]
        with self.assertRaises(ValueError): evaluate(d)
        d = packet(); d['cases'][0]['predictions'][-1]['external_processing'] = True
        with self.assertRaises(ValueError): evaluate(d)
        d = packet(); d['cases'][0]['input'] = 'changed original'
        with self.assertRaises(ValueError): evaluate(d)


if __name__ == '__main__': unittest.main()
