"""PCM helpers. Python 3.11/3.12 required for stateful audioop resampling."""
import audioop


class Resampler:
    def __init__(self, source, target):
        self.source, self.target, self.state = source, target, None

    def convert(self, pcm):
        if len(pcm) % 2:
            raise ValueError('PCM must contain whole 16-bit samples')
        if self.source == self.target:
            return pcm
        output, self.state = audioop.ratecv(pcm, 2, 1, self.source, self.target, self.state)
        return output


def chunks(pcm, sample_rate):
    # 200 ms chunks meet Exotel's 3200-byte minimum at 8 kHz.
    size = sample_rate * 2 // 5
    for index in range(0, len(pcm), size):
        yield pcm[index:index + size].ljust(size, b'\0')
