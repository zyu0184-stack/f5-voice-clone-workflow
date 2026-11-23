# 踩坑记录

按"症状 → 原因 → 处理"排。都是真踩过的，不是抄的报错清单。

## 1. `Library cublas64_12.dll is not found or cannot be loaded`

**症状**：faster-whisper 加载 CUDA 模型时崩，说找不到 cuBLAS。

**原因**：`ctranslate2` 的 CUDA 版本要 cuBLAS 12 和 cuDNN 9，torch 自带的那些不共享给它。

**处理**：两条路。装 NVIDIA 的 cuBLAS/cuDNN 运行库并把目录加进 `PATH`；或者干脆用 CPU：

```python
WhisperModel("models/whisper-turbo", device="cpu", compute_type="int8", cpu_threads=8)
```

20 分钟中文音频整片转写，CPU int8 大概几分钟，只用来挑片段完全够。

## 2. `ImportError: TorchCodec is required for load_with_torchcodec`

**症状**：`torchaudio.load()` 报这个，任何 wav 都读不了。

**原因**：torchaudio 2.9 之后把默认解码后端换成了 TorchCodec，它的 wheel 在 Windows 上不全。

**处理**：在 import 之后、用之前，把 `torchaudio.load` 换成 soundfile 实现。本仓库所有脚本都在顶部做了这件事：

```python
if not getattr(torchaudio, "_sf_patched", False):
    def _load(path, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(np.ascontiguousarray(data.T)), sr

    torchaudio.load = _load
    torchaudio._sf_patched = True
```

必须在 `from f5_tts.api import F5TTS` **之前**打，晚了 F5 已经把旧函数绑进去了。

## 3. `FileMetadataError: Distant resource does not seem to be on huggingface.co`

**症状**：`snapshot_download` 报这个，或者 `LocalEntryNotFoundError`。

**原因**：走 `hf-mirror.com` 时，镜像返回的 metadata 里缺字段，新版 `huggingface_hub` 校验不过。换镜像、设 `HF_ENDPOINT` 都没用。

**处理**：绕开 hub 的下载器，直接 curl：

```bash
curl -L --retry 3 -o models/F5TTS_v1_Base/model_1250000.safetensors \
  https://hf-mirror.com/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/model_1250000.safetensors
curl -L --retry 3 -o models/F5TTS_v1_Base/vocab.txt \
  https://hf-mirror.com/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/vocab.txt
```

下完把 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 打开，省得运行时再联网校验。

## 4. 装完 `datasets` 之后 transformers 罢工

**症状**：`huggingface-hub>=0.23.2,<1.0 is required ... but 2.4.0 is installed`。

**原因**：`datasets` 的新版会把 `huggingface-hub` 顶到 2.x，而 `transformers==4.46.3` 只认 0.2x。

**处理**：三个包一起 pin，别单独升：

```
transformers==4.46.3
huggingface-hub==0.26.2
datasets==2.21.0
```

`f5-tts` 用 `--no-deps` 装，然后手动补 `vocos` / `ema-pytorch` / `x-transformers` / `cached_path` / `pydub` / `unidecode` / `rjieba` / `wandb` / `accelerate`，这些是它 import 时才暴露的隐式依赖。

## 5. `AttributeError: 'F5TTS' object has no attribute 'model'`

**症状**：想查模型在不在 GPU 上，`next(tts.model.parameters())` 报错。

**原因**：`f5_tts.api.F5TTS` 是包装类，里面叫 `ema_model` / `model`（视版本），没有对外暴露统一的 `.model`。

**处理**：device 自己记。本仓库的 `f5_server.py` 在 `load_model()` 里把 device 存进 `STATE["device"]`，`/health` 直接读它。

## 6. 合成了但文件是空的 / 上层报"没有音频产出"

**症状**：调用 `synthesize()` 之后目标文件不存在。

**原因**：签名是 `synthesize(text, outFile, voice, delivery)`，顺序错成 `(text, voice, delivery)` 会把 voice 字符串当路径、把 dict 传进模型，服务端抛 `TypeError: unhashable type: 'dict'`。

**处理**：按顺序传，检查返回的 `path` 真的存在、字节数大于几百。`scripts/f5_server.py` 里对 `< 200` 字节的响应直接判失败。

## 7. Windows 上 curl 发中文，服务端收到乱码

**症状**：`bad_json: 'utf-8' codec can't decode byte 0xb1 in position ...`。

**原因**：cmd/PowerShell 的默认代码页是 GBK，`curl -d '{"text":"中文"}'` 按 GBK 编码发出去。

**处理**：用 python 发（`scripts/tts_client.py` 就是干这个的），或者把 JSON 写进文件：

```bash
curl -X POST http://127.0.0.1:18231/tts \
  -H "Content-Type: application/json" --data-binary @payload.json
```

## 8. 服务起了又没了

**症状**：`Start-Process` 拉起来的进程，关掉终端或者父 shell 退出后就消失了。

**原因**：Windows 上子进程默认跟父进程绑在一起，`WindowStyle Hidden` 不改变这个。

**处理**：用 `DETACHED_PROCESS(0x8) | CREATE_NEW_PROCESS_GROUP(0x200)`，POSIX 上用 `start_new_session=True`。`scripts/start_f5.py` 已经这么写，并且拉完会轮询 `/health`，最多等 180 秒。

模型加载慢的时候（冷启动 30 秒上下）别以为它死了，看 `work/f5_console.log` 里的 `[boot] listening`。

## 9. 改了代码，重启了宿主，还是旧行为

**症状**：改了插件里的 JS，把插件禁用再启用，接口返回还是老样子。

**原因**：Node 的 ESM 模块缓存 + 宿主复用 fiber，`disable → enable` 不会重新 import 模块。

**处理**：整进程重启。或者像本仓库的接入层那样，把逻辑放进**每次调用都新 spawn 的子进程脚本**里——那个进程每次都是新的，改文件立刻生效。

## 10. venv 能整体搬目录吗

**能**。`pyvenv.cfg` 里的 `home` 指向系统 python，venv 自己的位置由可执行文件路径推导。整个 `.venv` 目录移到别处，`torch.cuda.is_available()` 照样是 True。

搬完记得改依赖它的那些绝对路径（本仓库的 `F5_TTS_PY` / `F5_TTS_SCRIPT` / `F5_TTS_LOG` 环境变量就是给这种情况留的）。

## 11. 挑片段挑到了广告

**症状**：自动挑出来的"最佳片段"是片头的广告词。

**原因**：广告的发音往往比正片更密集、更干净，按覆盖率打分必然赢。

**处理**：先跑 `full_asr.py` 看文本，把片头片尾的时间范围排除掉，再手动 `cut_span.py` 指定秒数。自动挑只当候选池用。

## 12. 克隆出来"像又不像"

**症状**：音色对了，但断句、重音、语速都不对。

**原因**：`ref_text` 和音频没逐字对上。ASR 在口音素材上经常把字写错，差一个字韵律就飘。

**处理**：把参考音频听一遍，逐字抄。标点可以改（标点影响断句），字一个都不能改，"嗯""啊"这类语气词也要留着。

## 13. 输出采样率不是 24 kHz

**症状**：上层拿到音频，播放速度不对或者音调变形。

**原因**：F5 输出 24 kHz，vocos 声码器决定的。上层的音频管道如果假设 16 kHz 或 44.1 kHz，就会出问题。

**处理**：合成前确认下游期望的采样率，需要就转：

```bash
ffmpeg -i in.wav -ar 48000 out.wav
```
