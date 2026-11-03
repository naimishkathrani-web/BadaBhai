import re


class SentenceBuffer:
    """Keep token boundaries and Hindi punctuation intact; bound long unpunctuated text."""
    def __init__(self):
        self.pending = ''

    def feed(self, text):
        self.pending += text
        result = []
        while self.pending:
            boundary = re.search(r'[!?।](?:\s|$)|\.(?:\s+)', self.pending)
            if boundary:
                end = boundary.end()
            elif len(self.pending) > 160:
                end = self.pending.rfind(' ', 60, 150)
                if end < 0:
                    break
            else:
                break
            sentence, self.pending = self.pending[:end].strip(), self.pending[end:].lstrip()
            if sentence:
                result.append(sentence)
        return result

    def finish(self):
        tail, self.pending = self.pending.strip(), ''
        return [tail] if tail else []
