import os
os.environ['MMS_ALLOW_DOWNLOAD'] = '1'
from app.voice import synthesize

for language, text in [('en', 'Hello. Ask me a question.'), ('hi', 'नमस्ते। अपना सवाल पूछिए।')]:
    pcm = synthesize(text, language)
    assert len(pcm) > 3200
    print(f'{language}: voice ready ({len(pcm) // 16000:.1f} seconds)')
