import struct
import pickle
import zstd

class EventLogFile:
    def __init__(self, filename, mode='r'):
        ' mode in "rw" '
        self.mode = mode
        self.filename = filename
        if   mode == 'r': mode += 'b'
        elif mode == 'w': mode += 'b+'
        else: raise Exception('unknown file mode %r' % self.mode)
        self._mode = mode
        self.f = None

    def open(self):
        assert self.f is None
        self.f = open(self.filename, self._mode)

    def write(self, obj):
        assert self.mode == 'w', self.mode
        d = zstd.compress(pickle.dumps(obj))
        self.f.write(struct.pack('!I', len(d)) + d)

    def read(self):
        assert self.mode == 'r', self.mode
        d = self.f.read(4)
        if not d: return None
        pktlen, = struct.unpack('!I', d)
        obj = pickle.loads(zstd.decompress(self.f.read(pktlen)))
        return obj

    def close(self):
        self.f.close()
        self.f = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *a):
        try: self.close()
        except: pass

