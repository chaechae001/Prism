"""Read-only readiness check for the DB news and article-scoped chat flow."""
import argparse
import json
import os


def main(argv=None):
    parser = argparse.ArgumentParser(description='DB 뉴스·본문·AI 설정 읽기 전용 점검')
    parser.add_argument('--namespace', default='scheduled-local-test')
    args = parser.parse_args(argv)
    # A dedicated DB check never adopts the fixture source from a local file.
    os.environ['PRISM_DATA_SOURCE'] = 'cluster-db'
    os.environ['PRISM_CLUSTER_NAMESPACE'] = args.namespace
    try:
        from .config import load_environment
        load_environment()
        from .connection_repository import load_snapshot
        from .services.cluster_context import chat_cluster_bodies
        from .chat.providers import settings
        snapshot = load_snapshot('cluster-db')
        if not snapshot.stories:
            print(json.dumps({'ready':False,'message':'DB에 활성 뉴스가 없습니다. 수집·저장 완료 배치를 확인해주세요.'},ensure_ascii=False))
            return 1
        selected = max(snapshot.stories,key=lambda story:len(story.articles))
        bodies = chat_cluster_bodies(selected)
        try:
            provider,key,model,_ = settings()
            configured = bool(key and model)
        except ValueError:
            provider,configured = 'unconfigured',False
        result = dict(ready=bool(bodies) and configured,data_source='cluster-db',
            stories=len(snapshot.stories),articles=sum(len(s.articles) for s in snapshot.stories),
            checked_story_id=selected.id,selected_articles=len(selected.articles),
            permitted_bodies=len(bodies),context_characters=sum(len(b['text']) for b in bodies),
            provider=provider,provider_settings_present=configured,llm_calls=0,database_writes=0,
            message='DB 뉴스·선택 기사 본문·AI 설정을 확인했습니다. 실제 대화는 웹에서 검증해주세요.'
                    if configured else 'AI 제공자 설정을 확인해주세요. 키와 모델은 서버의 비공개 환경 파일에 저장합니다.')
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ready'] else 1
    except Exception as exc:
        # Do not echo SQL parameters, credentials, response bodies or local file contents.
        print(json.dumps(dict(ready=False,error_type=type(exc).__name__,
            message='DB 접속·군집 배치·본문 허용 상태를 확인해주세요. 접속 정보와 원문은 출력하지 않습니다.'),ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
