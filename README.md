# 本地音色克隆引擎

用一张 8 GB 显卡在自己机器上跑 F5-TTS，把一段长音频变成可用的音色，再用一个常驻 HTTP 服务把它接到任意应用里。

三样东西：

- **一个常驻服务**。模型只加载一次，之后每句合成 3～5 秒，走 HTTP。
- **一条切素材的流水线**。长音频里混着广告、长静音、气声、背景音乐，直接丢进去当参考，克隆出来当然不像。这里管的是怎么找到那 10 秒干净人声。
- **两个接入层**。`dsh-voice-mini`（DSH 的本地朗读插件）和任意愿意说 HTTP 的程序。

---

## 为什么不用云端克隆

在线 TTS 的音色是平台给的，换不了。想换成某个具体的人，要么走平台的克隆接口（要上传声音、要审核、要钱），要么自己在本机做。

自己做的代价是一次性搭建，好处是之后每句都免费、离线、不限量，合成的内容也不出本机。

代价里有几个真实的门槛，这套仓库就是踩过之后留下的记录：

| 门槛 | 表现 | 处理 |
|---|---|---|
| 参考音频质量 | 拿一条 20 分钟的成品音频直接当参考，出来不像 | 切成 10 秒、无广告无静音的片段 |
| 参考文本必须逐字对 | 差一个字，韵律就飘 | ASR 转写后人工改标点，不改字 |
| 环境版本互相打架 | transformers / datasets / huggingface-hub 连环报错 | 见 `docs/troubleshooting.md` |
| 服务会死 | 进程没了，上层每次合成都失败 | `start_f5.py` 拉成脱离态，上层探活自愈 |

---

## 实测环境

| 项 | 值 |
|---|---|
| GPU | RTX 4070 Laptop，8 GB 显存 |
| Python | 3.11.9 |
| torch | 2.11.0+cu128 |
| 模型权重 | F5TTS_v1_Base `model_1250000.safetensors`，1.35 GB |
| 声码器 | vocos-mel-24khz，54 MB |
| 模型加载 | 冷启 30 s 上下，权重在系统缓存里时 1.5 s |
| 单句合成（24 字中文） | 3.2～5.5 s，输出 24 kHz 单声道 |

显存占用随句长涨，8 GB 卡跑 30 字以内的句子没有压力；一次只能跑一句，服务里用一把锁串行，同一张卡上并发只会互相拖慢。

---

## 结构

```
scripts/
  f5_server.py      常驻 HTTP 服务（/health /voices /tts /tts.json）
  start_f5.py       把服务拉成脱离态进程，父进程退出也不影响
  tts_client.py     命令行客户端，验证链路
  clone_say.py      单次合成，给一句话和一个参考
  say.py            一次加载，按句批量合成
  verify_wav.py     合成完用 ASR 回读，确认说的是那句话
pipeline/
  ingest_voice.py   新音频入库：ffprobe → 32 kHz 单声道工作副本 → 统计
  pick_clip.py      按覆盖率和平坦度自动挑 10 秒窗
  cut_span.py       按秒数精确切，带轻降噪
  full_asr.py       整片转写，给挑片段和逐字稿用
  probe_voice.py    VAD 扫人声段
  analyze_mix.py    帧级 rms / 谱平坦度 / 立体声真假
  clip_select.py    早期按覆盖率挑窗的版本，留着对照
integrations/
  dsh-voice-mini/   把 clone 后端接进该插件的适配脚本
config/
  voices.example.json
docs/
  troubleshooting.md
```

---

## 装

### 1. 前置

系统里要有 python 3.10+、ffmpeg、ffprobe。Windows 上 `winget install ffmpeg` 或 scoop 都行，装完确认 `ffmpeg -version` 能跑。

### 2. 建环境

```bash
bash setup_tts.sh
```

脚本做四件事：建 venv（复用系统已装的 torch，省一次 2 GB 下载）、装 f5-tts 与依赖、下载 F5TTS_v1_Base 和 vocos 声码器、验证 import。

国内网络默认走 `hf-mirror.com`。huggingface_hub 自己的下载器在这个镜像上会报 `FileMetadataError`，真要手下就用 `curl -L`：

```bash
curl -L --retry 3 -o models/F5TTS_v1_Base/model_1250000.safetensors \
  https://hf-mirror.com/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/model_1250000.safetensors
```

### 3. 配音色

复制 `config/voices.example.json` 到仓库根目录的 `voices.json`，把 `ref` 指向你切好的参考音频，`ref_text` 填这段音频里**逐字**说的内容。

```json
{
  "speaker_a": {
    "name": "说话人A",
    "ref": "refs/speaker_a_ref.wav",
    "ref_text": "这段参考音频里逐字说的那句话。",
    "speed": 1.0,
    "nfe": 32,
    "cfg": 2.0
  }
}
```

服务每次请求前会比对 `voices.json` 的 mtime，改了自动重载，不用重启。

### 4. 起服务

```bash
python scripts/start_f5.py
# spawned pid=12345 port=18231 log=work/f5_console.log
# ready on 18231 after 31.2s
```

看到 `ready` 就可以用。`start_f5.py` 用 `DETACHED_PROCESS`（Windows）/ `start_new_session`（POSIX）把进程完全摘出去，关掉终端不影响它。

### 5. 试一句

```bash
python scripts/tts_client.py "这句话应该用参考音频里的音色说出来。" speaker_a out/test.wav
# OK out/test.wav bytes=147500 sr=24000 ms=4557 voice=说话人A wall=4.57s
```

---

## 素材怎么切

这一步决定最后像不像，比换模型有用得多。

### 第一步，入库看底子

```bash
python pipeline/ingest_voice.py long_take.mp3 speaker_a
```

输出：时长、整体 rms、峰值、语音电平、静音电平、谱平坦度。

判断标准，来自实测对比：

| 指标 | 好素材 | 差素材 |
|---|---|---|
| 底噪（quiet_dbfs） | −70 dBFS 以下 | −33 dBFS 附近 |
| 谱平坦度（flatness_mean） | 0.2～0.33 | 0.4 以上（气声、混响糊在一起） |
| 立体声 | 左右真有差异 | mid/side 差 0.3～1.5 dB，假立体声 |

同一个人录的两条，棚里干声和直播录音差 40 dB 底噪，克隆出来是两回事。

### 第二步，找干净片段

```bash
python pipeline/full_asr.py speaker_a --beam 1
python pipeline/pick_clip.py speaker_a 说话人A --win 10 --top 5
```

`full_asr` 出整片时间戳文本，先看一遍开头和结尾——成品音频的**广告通常在片头 20 秒和片尾**，那里的发音往往最密集，纯按能量挑一定挑到广告。

`pick_clip` 的打分是 `覆盖率 − 0.6 × 超出的平坦度`，覆盖率高说明一直在说话，平坦度高说明气声重。两个权重都写在函数里，想换先改 `rolling()`。

### 第三步，切并降噪

```bash
python pipeline/cut_span.py speaker_a 44.4 55.5 refs/speaker_a_ref.wav --denoise
```

处理链：

```
highpass=f=70, afftdn=nr=10:nf=-45, loudnorm=I=-19:TP=-2:LRA=6
```

70 Hz 以下砍掉（人声基频最低也就 80 上下），`afftdn` 轻降噪，最后统一到 −19 LUFS 峰值 −2 dB。**别做重度降噪**，零样本克隆需要保留气息和齿音，压干净了反而不像。

### 第四步，抄逐字稿

`ref_text` 和音频必须逐字对应，包括"嗯""啊"。

ASR 出来的东西要人工过一遍。中文口音素材常见错法：

| 听到的 | ASR 常写成 |
|---|---|
| 专属 | 真属 / 准属 |
| 公务舱 | 公务仓 |
| 航司 | 杭司 |
| 服务顾客 | 佛物故科 |

错一个字，克隆的韵律就开始飘。

### 第五步，验收

```bash
python scripts/verify_wav.py out/test.wav
```

用 faster-whisper 把合成结果转回文字，和原文比。差一两个字是同音误差，整句不对就是参考音频出了问题。

---

## 接进应用

### HTTP

任何程序只要能发 POST：

```bash
curl -X POST http://127.0.0.1:18231/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"要合成的话","voice":"speaker_a","speed":1.0}'
```

拿到的是 `audio/wav`，24 kHz 单声道 PCM16。响应头带 `X-TTS-Sr`、`X-TTS-Ms`、`X-TTS-Voice`。

**Windows 上用 curl 发中文会踩坑**：cmd 默认 GBK，JSON 里的中文变成乱码，服务端报 `bad_json: 'utf-8' codec can't decode byte 0xb1`。用 `scripts/tts_client.py` 发，或者写文件再 `--data-binary @file.json`。

### dsh-voice-mini

见 `integrations/dsh-voice-mini/README.md`。核心是把该插件的 `scripts/synth-kokoro.mjs` 换成转发到本服务的版本，然后用插件的 `/config` 接口把后端切到 `clone`。

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | `{"ok":true,"loaded":true,"device":"cuda","calls":123,"voices":["speaker_a"]}` |
| GET | `/voices` | 注册表内容，`ref` 显示为相对仓库根的路径 |
| POST | `/tts` | body `{text, voice, speed, nfe, cfg, seed}` → `audio/wav` |
| POST | `/tts.json` | 同上，写到 `out/` 并回 JSON，调试用 |

`voice` 可以给注册表里的键，也可以直接给 `ref` + `ref_text` 内联。`speed` / `nfe` / `cfg` 单条可覆盖。`nfe` 默认 32，调到 16 快一倍但音质可见下降；`cfg` 2.0 是平衡点，调高更贴参考但容易发硬。

---

## 已知问题

全在 `docs/troubleshooting.md`，这里列最常见的三条：

1. `Library cublas64_12.dll is not found` —— faster-whisper 走 CUDA 时缺 cuBLAS，改 CPU/int8 或补 CUDA 运行库。
2. `ImportError: TorchCodec is required` —— torchaudio 2.11 改了默认解码后端，本仓库的脚本已经在 import 前把 `torchaudio.load` 换成 soundfile。
3. `huggingface-hub 2.x` 和 `transformers 4.46` 打架 —— 装 `datasets` 时会把 hub 顶上去，pin 住 `huggingface-hub==0.26.2`。

---

## 许可与素材

代码 MIT，见 `LICENSE`。

依赖项的许可证以各自仓库为准：F5-TTS 的代码是 MIT，其发布的预训练权重另有条款（当前为非商用），vocos、faster-whisper 是 MIT，Kokoro-82M 是 Apache-2.0。要商用先自己核对一遍权重许可。

**仓库里不含任何音频、模型权重、人名或音色。** 参考音频请使用你本人录制的、或已获得授权的、或公有领域的声音。用别人的录音做音色克隆，涉及声音权益，自己判断。

`/tts` 默认不记录请求内容。调试时加 `--request-log` 才会把每次请求（含全文）写进 `work/f5_requests.jsonl`。
