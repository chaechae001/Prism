# E5 모델 준비

군집분석 Python 코드는 `analysis/news_clustering`에 포함되어 있습니다. 사전 학습 가중치는 아래 고정 버전에서 별도로 받습니다. 정기 작업자와 API가 모델을 자동 다운로드하지는 않습니다.

- 모델: [Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small/tree/761b726dd34fb83930e26aab4e9ac3899aa1fa78)
- revision: `761b726dd34fb83930e26aab4e9ac3899aa1fa78`
- 로컬 폴더: 프로젝트 루트의 `.models/multilingual-e5-small`

| 파일 | 바이트 | SHA-256 |
|---|---:|---|
| tokenizer.json | 17082730 | 0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39 |
| onnx/model_quantized.onnx | 118308185 | f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193 |

`requirements-clustering-dev.txt`를 설치한 후, 프로젝트 루트의 PowerShell에서 다음 명령을 명시적으로 실행합니다. 공개 모델을 받으므로 Hugging Face 토큰을 지정하지 않습니다.

```powershell
@'
from hashlib import sha256
from pathlib import Path
from huggingface_hub import hf_hub_download

revision = '761b726dd34fb83930e26aab4e9ac3899aa1fa78'
expected = {
    'tokenizer.json': '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39',
    'onnx/model_quantized.onnx': 'f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193',
}
for filename, checksum in expected.items():
    file = Path(hf_hub_download(
        repo_id='Xenova/multilingual-e5-small', revision=revision,
        filename=filename, local_dir='.models/multilingual-e5-small', token=False))
    assert sha256(file.read_bytes()).hexdigest() == checksum, filename
    print(filename, 'verified')
'@ | .\.venv\Scripts\python.exe -
```

ONNX 파일은 약 113MiB입니다. [GitHub는 일반 Git 파일 100MiB 초과를 차단](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)하므로 가중치는 Git에 포함하지 않고 버전과 해시로 재현합니다. 이번에 공유하는 기사 원문·군집 결과·벡터는 `testdata/clustering`에 있습니다.

```powershell
.\.venv\Scripts\python.exe -m backend.app.clustering `
  --input examples/clustering-analyst.synthetic.json `
  --output-dir clustering-output/synthetic-v2 `
  --model-dir .models/multilingual-e5-small
```
