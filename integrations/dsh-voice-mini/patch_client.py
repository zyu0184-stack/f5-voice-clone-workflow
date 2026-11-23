# -*- coding: utf-8 -*-
"""把 clone 后端接进 dsh-voice-mini 的前端 bundle。"""
import os
import pathlib
import sys

_DEFAULT = pathlib.Path.home() / ".dsh" / "profiles" / "desktop" / "node_modules" / "dsh-voice-mini" / "lib"
LIB = pathlib.Path(os.environ.get("VOICE_MINI_LIB") or _DEFAULT)
p = LIB / "client.js"
s = p.read_text(encoding="utf-8")
orig = s
steps = []

# 1) 每个引擎的音色白名单
old_me = ('me={edge:["zh-CN-XiaoxiaoNeural","zh-CN-XiaoyiNeural","zh-CN-YunyangNeural",'
          '"zh-CN-YunjianNeural","en-US-AriaNeural","en-US-ChristopherNeural"],'
          'kokoro:["af_heart","af_alloy","bm_fable","am_adam"],'
          'say:["Tingting","Sinji","Meijia","Samantha"],fake:[]}')
new_me = ('me={edge:["zh-CN-XiaoxiaoNeural","zh-CN-XiaoyiNeural","zh-CN-YunyangNeural",'
          '"zh-CN-YunjianNeural","en-US-AriaNeural","en-US-ChristopherNeural"],'
          'kokoro:["af_heart","af_alloy","bm_fable","am_adam"],'
          'say:["Tingting","Sinji","Meijia","Samantha"],'
          'clone:["speaker_a","speaker_a_tease","speaker_a_hard","speaker_a_soft","speaker_a_shame"],fake:[]}')
if old_me in s and 'clone:[' not in s:
    s = s.replace(old_me, new_me, 1)
    steps.append("whitelist")
else:
    steps.append("whitelist:skip")

# 2) 引擎下拉框
old_opt = 'options:["edge","kokoro","say","fake"]'
new_opt = 'options:["edge","kokoro","say","clone","fake"]'
if old_opt in s:
    s = s.replace(old_opt, new_opt, 1)
    steps.append("dropdown")
else:
    steps.append("dropdown:skip")

# 3) 音色显示名：插在 am_adam:"Adam", 之后
anchor = 'am_adam:"Adam",'
add = ('speaker_a:"说话人A",speaker_a_tease:"说话人A·嘲",speaker_a_hard:"说话人A·狠",'
       'speaker_a_soft:"说话人A·轻",speaker_a_shame:"说话人A·羞",clone:"本机克隆",')
if anchor in s and 'speaker_a:"说话人A"' not in s:
    s = s.replace(anchor, anchor + add, 1)
    steps.append("names")
else:
    steps.append("names:skip")

if s != orig:
    p.write_text(s, encoding="utf-8")
print(",".join(steps))
sys.exit(0)
