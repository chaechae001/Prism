"""Pinned local E5 ONNX retrieval encoding; no network or model download."""
from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
import threading
import numpy as np
from ..config import ROOT


class LocalE5:
    def __init__(self,path=None):
        from tokenizers import Tokenizer
        import onnxruntime as ort
        path=Path(path or os.getenv('PRISM_E5_MODEL_DIR',str(ROOT/'.models/multilingual-e5-small'))).resolve()
        files=[path/'tokenizer.json',path/'onnx/model_quantized.onnx']
        if not all(f.is_file() for f in files): raise ValueError('로컬 E5 모델 파일을 준비해주세요. 자동 다운로드는 하지 않습니다.')
        h=sha256()
        for f in files:
            with f.open('rb') as stream:
                for block in iter(lambda:stream.read(1048576),b''): h.update(block)
        self.model_id='e5-small-384/query-passage/v1:'+h.hexdigest()
        self.tokenizer=Tokenizer.from_file(str(files[0]));self.tokenizer.no_truncation();self.tokenizer.no_padding()
        self.lock=threading.Lock()
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(files[1]),sess_options=options,providers=['CPUExecutionProvider'])

    def chunks(self,text):
        with self.lock:
            self.tokenizer.no_truncation();self.tokenizer.no_padding()
            offsets=self.tokenizer.encode(text,add_special_tokens=False).offsets
        return [(offsets[i][0],offsets[min(i+320,len(offsets))-1][1]) for i in range(0,len(offsets),272) if offsets[i][0]<offsets[min(i+320,len(offsets))-1][1]]

    def encode(self,texts,*,query=False):
        vectors=[]
        with self.lock:
            t=self.tokenizer;t.enable_truncation(max_length=512)
            pad='<pad>' if t.token_to_id('<pad>') is not None else '[PAD]'
            t.enable_padding(pad_id=t.token_to_id(pad),pad_token=pad)
            for i in range(0,len(texts),8):
                batch=t.encode_batch([('query: ' if query else 'passage: ')+x for x in texts[i:i+8]])
                inputs={k:np.asarray(v,dtype=np.int64) for k,v in {
                    'input_ids':[x.ids for x in batch],'attention_mask':[x.attention_mask for x in batch],'token_type_ids':[x.type_ids for x in batch]}.items()}
                names={x.name for x in self.session.get_inputs()}
                hidden=self.session.run(None,{k:v for k,v in inputs.items() if k in names})[0]
                mask=inputs['attention_mask'][...,None].astype(np.float32)
                pooled=(hidden*mask).sum(1)/np.maximum(mask.sum(1),1)
                pooled/=np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12)
                vectors.extend(pooled.astype(np.float32))
        return np.asarray(vectors,dtype=np.float32).reshape((-1,384))


@lru_cache(maxsize=1)
def encoder():
    provider=os.getenv('PRISM_EMBEDDING_PROVIDER','e5')
    if provider=='e5': return LocalE5()
    if provider=='ollama': return OllamaEmbedding()
    raise ValueError('지원하지 않는 임베딩 제공자입니다.')


class OllamaEmbedding:
    """Existing BGE-M3 only; exact character offsets and immutable model identity."""
    def __init__(self):
        import httpx
        from .ollama import endpoint
        self.url=endpoint();self.model=os.getenv('OLLAMA_EMBED_MODEL','bge-m3:latest')
        try:
            with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as c:
                r=c.get(self.url+'/api/tags');r.raise_for_status()
            installed=next((m for m in r.json()['models'] if m.get('name')==self.model),None)
        except (httpx.HTTPError,KeyError,TypeError):
            raise ValueError('로컬 임베딩 모델 목록을 읽지 못했습니다.') from None
        if not installed or not self.model.startswith('bge-m3:') or not installed.get('digest'):
            raise ValueError('설치된 BGE-M3 임베딩 모델을 선택해주세요.')
        self.digest=installed['digest']
        self.model_id='ollama-bge-m3-1024/chars600-overlap80/v1:'+installed['digest']

    def chunks(self,text):
        return [(start,min(start+600,len(text))) for start in range(0,len(text),520)]

    def encode(self,texts,*,query=False):
        import httpx
        try:return self._encode(texts)
        except (httpx.HTTPError,KeyError,TypeError):
            raise ValueError('로컬 임베딩 서버가 응답하지 않거나 모델 응답이 잘못되었습니다.') from None

    def _encode(self,texts):
        import httpx
        rows=[]
        with httpx.Client(timeout=90,trust_env=False,follow_redirects=False) as c:
            tags=c.get(self.url+'/api/tags');tags.raise_for_status()
            if not any(m.get('name')==self.model and m.get('digest')==self.digest for m in tags.json()['models']):
                raise ValueError('임베딩 모델이 바뀌었습니다. 서버를 재시작해주세요.')
            for i in range(0,len(texts),1):
                r=c.post(self.url+'/api/embed',json={'model':self.model,'input':texts[i:i+1],
                    'truncate':False,'keep_alive':'2m'})
                r.raise_for_status();vectors=np.asarray(r.json()['embeddings'],dtype=np.float32)
                if vectors.shape!=(len(texts[i:i+1]),1024) or not np.isfinite(vectors).all():
                    raise ValueError('BGE-M3 임베딩 응답이 예상과 다릅니다.')
                lengths=np.linalg.norm(vectors,axis=1,keepdims=True)
                if np.any(lengths<1e-12):raise ValueError('빈 임베딩 벡터입니다.')
                rows.extend(vectors/lengths)
        return np.asarray(rows,dtype=np.float32).reshape((-1,1024))
