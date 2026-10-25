"""Explicit storage commands; prepare is offline and store defaults to a read-only plan."""
import argparse
import json
from pathlib import Path
import sys

from .bundle import prepare_bundle, write_bundle, load_json, summarize_bundle
from .repository import schema_status, install_schema, plan_bundle, store_bundle


def main(argv=None):
    parser=argparse.ArgumentParser(description='Private original-body, photo-URL and cluster batch storage. No LLM or publication.')
    commands=parser.add_subparsers(dest='command',required=True)
    schema=commands.add_parser('schema',help='Inspect only; --apply installs four isolated private tables once')
    schema.add_argument('--apply',action='store_true')
    prepare=commands.add_parser('prepare',help='Offline validation and a fresh local private batch file')
    prepare.add_argument('--results-dir',type=Path,required=True)
    prepare.add_argument('--namespace',required=True)
    prepare.add_argument('--images',type=Path)
    prepare.add_argument('--output',type=Path,required=True)
    for name in ('plan','store'):
        command=commands.add_parser(name)
        command.add_argument('--batch',type=Path,required=True)
        if name=='store':command.add_argument('--apply',action='store_true',help='Explicitly insert the validated batch in one transaction')
    args=parser.parse_args(argv)
    try:
        if args.command=='schema':
            result=install_schema() if args.apply else schema_status()
        elif args.command=='prepare':
            value=prepare_bundle(args.results_dir,namespace=args.namespace,image_manifest=args.images)
            write_bundle(value,args.output)
            result=dict(**summarize_bundle(value),status='prepared')
        else:
            value=load_json(args.batch.read_bytes())
            result=store_bundle(value) if args.command=='store' and args.apply else plan_bundle(value)
        print(json.dumps(result,ensure_ascii=True))
        return 0
    except (OSError,ValueError,KeyError,TypeError,RecursionError):
        print(json.dumps(dict(error='CLUSTER_STORAGE_REJECTED',automatic_retry=False)),file=sys.stderr)
        return 2
    except Exception as exc:
        # SQL errors may contain credentials or row contents. Never print their text or parameters.
        print(json.dumps(dict(error='CLUSTER_STORAGE_NOT_CONFIRMED',error_type=type(exc).__name__,
            automatic_retry=False,recovery='Use plan with the same unchanged batch to inspect the result')),file=sys.stderr)
        return 3


if __name__=='__main__':raise SystemExit(main())
