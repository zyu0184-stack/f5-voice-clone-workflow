# 把 clone 后端接进 dsh-voice-mini

`dsh-voice-mini` 原本支持 edge（微软云）、kokoro（本地英文）、say（macOS）、fake 四个后端。这里做的是加第五个：`clone`，转发到本仓库的 F5 服务。

这个目录里只有适配层，不含该插件的源码。下面的改动都发生在你本地安装的副本上，升级插件会被覆盖，升级后重跑一遍。

## 涉及的文件

| 文件 | 作用 |
|---|---|
| `synth-kokoro.mjs` | 替换插件里的同名脚本，把请求转发到 F5 `/tts`，失败回落原逻辑 |
| `patch_client.py` | 改前端 bundle：白名单、下拉框、音色显示名 |
| `vm_api.py` | 从终端调插件的 HTTP 接口（受 DSH 本地 token 保护，curl 打不进去） |

## 为什么从脚本下手

插件的 host 代码在 DSH 进程里跑，改了 ESM 模块不重启不生效。但 `scripts/synth-kokoro.mjs` 是**每次合成时新 spawn 一个 node 进程**在跑，改文件立刻生效。

所以最小改动是：让这个子进程去说 HTTP。

```
插件 host → spawn node scripts/synth-kokoro.mjs <text> <out.wav> <voice> <speed>
          → 本目录的 synth-kokoro.mjs → POST http://127.0.0.1:18231/tts
```

契约保持原样：`<text> <out.wav> [voice] [speed]`，成功就退出码 0，输出文件必须存在且够大。

## 三步

### 1. 备份并替换脚本

```bash
PKG=~/.dsh/profiles/desktop/node_modules/dsh-voice-mini
cp "$PKG/scripts/synth-kokoro.mjs" "$PKG/scripts/synth-kokoro.local.mjs"
cp integrations/dsh-voice-mini/synth-kokoro.mjs "$PKG/scripts/synth-kokoro.mjs"
```

第一行是关键：原脚本要留成 `synth-kokoro.local.mjs`，新脚本在 F5 不可达时会回落调它。

### 2. 改前端 bundle

```bash
python integrations/dsh-voice-mini/patch_client.py
# whitelist,dropdown,names
```

脚本幂等，跑第二遍会输出 `whitelist:skip,dropdown:skip,names:skip`。目标目录默认 `~/.dsh/profiles/desktop/node_modules/dsh-voice-mini/lib`，不对就设 `VOICE_MINI_LIB`。

### 3. 加后端枚举

`lib/tts.js` 里的 `makeBackend()` 要加一个 case，`lib/index.js` 里有三处枚举要同步（配置 schema、扩展名映射、`/config` 的 POST 白名单）。照下面这四条改：

```
1) lib/index.js  backend: z.union(['edge','kokoro','say','clone','fake'])
2) lib/index.js  extForBackend(): clone 返回 'wav'
3) lib/index.js  POST /config 的白名单加 'clone'
4) lib/tts.js    makeBackend(): case 'clone' -> new CloneBackend()
```

`CloneBackend.synthesize(text, outFile, voice, delivery)` 里最省事的做法是走 HTTP，超时给足（模型首句要几秒）：

```js
const r = await fetch(`${CLONE_URL}/tts`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text, voice, speed: clamp(1 + delivery.ratePct / 100, 0.7, 1.4) }),
  signal: AbortSignal.timeout(300_000),
})
```

改完重启 DSH。这一步绕不过去。

## 三个会让人白查两小时的坑

### 1. `voiceMode` 的默认值是 `per-session`

配置里 `voice` 设成 `speaker_b`，`/state` 看着也对，但真正发声的是 `sessionVoice`。默认模式下 `voice` 只是新会话的基准值，当前会话还留在旧音色上。

```bash
python integrations/dsh-voice-mini/vm_api.py config '{"voiceMode":"fixed","voice":"speaker_b"}'
python integrations/dsh-voice-mini/vm_api.py state | grep -i sessionVoice
```

要两个都变过来才算真的换了。

### 2. `voicePalette` 非空时，界面上没有音色下拉

前端是这么写的：

```
voicePalette.length > 0 ? 文本框（英文键名，onBlur 提交） : 音色下拉
```

所以只要你手动指定过一次调色板，设置面板里的下拉就消失了，看到的是一串英文键名。以为自己加的音色没生效，其实它在池子里。

```bash
python integrations/dsh-voice-mini/vm_api.py config '{"voicePalette":[]}'
```

清空之后下拉回来，`effectivePalette` 会按语言过滤后自动生成。

### 3. 默认调色板按语言过滤，`locale=zh` 时会把非中文键名滤掉

`defaultPalette(backend, locale)` 在 `locale==='zh'` 时只留 `startsWith('zh')` 的键。音色键叫 `speaker_a` 就被当成外语音色滤掉；如果过滤结果为空，函数会回落成全部——所以这个 bug 有时显形有时不显形，取决于你那几个键长什么样。

```js
if (backend === 'clone') return all  // 克隆后端的键是说话人名，不是语言标签
```

## 验证

```bash
# 1. 服务活着
curl -s http://127.0.0.1:18231/health

# 2. 插件认这个后端
python integrations/dsh-voice-mini/vm_api.py config '{"backend":"clone"}'

# 3. 让它说一句
python integrations/dsh-voice-mini/vm_api.py test "这句话应该用克隆的声音说出来。"

# 4. 回读验收
python scripts/verify_wav.py ~/.dsh/voice-mini/<返回的 url 文件名>
```

第 3 步返回 `{"ok":true,"ms":...,"url":"/voice-mini/audio/....wav"}` 就说明链路通了。`ms` 在 2000～6000 之间是正常的（含模型推理）。

## 权限

插件的 HTTP 接口要求 DSH 本地 token，`vm_api.py` 从 `~/.dsh/voice-mini/runtime.json` 读 `origin` 和 `token`。DSH 每次重启端口会变，这个文件会被重写，脚本每次调用都重新读，不用管。
