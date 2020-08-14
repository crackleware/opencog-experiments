import sys
import os
import re
import subprocess
import array
import time
import threading
import random
import numpy as np

from event_log_file import EventLogFile

output_filename = 'vm_page_flags.out'
period = 0.1 # s
experiment_name = None
fifo_filename = None

while sys.argv[1].startswith('-'):
    if   sys.argv[1] == '--output': output_filename = sys.argv[2]
    elif sys.argv[1] == '--period': period = float(sys.argv[2])
    elif sys.argv[1] == '--name': experiment_name = sys.argv[2]
    elif sys.argv[1] == '--fifo': fifo_filename = sys.argv[2]
    else:
        raise Exception('unknown option '+sys.argv[1])
    del sys.argv[1:3]

print('output_filename:', output_filename)
if fifo_filename: print('fifo_filename:', fifo_filename)
print('period:', period)

cmd = sys.argv[1:]
print('cmd:', cmd)

page_size = int(subprocess.check_output('getconf PAGE_SIZE', shell=True).decode('utf8'))
print('page_size:', page_size)

class MarkerReader(threading.Thread):
    def __init__(self, fifo_filename):
        super().__init__()
        self.fifo_filename = fifo_filename
        try: os.unlink(self.fifo_filename)
        except: pass
        os.mkfifo(self.fifo_filename)
        self.marker = None
        self.setDaemon(True)
        self.start()
    def run(self):
        while 1:
            with open(self.fifo_filename) as fifo:
                while 1:
                    m = fifo.read().strip()
                    if not m: break
                    self.marker = m
                    print('marker:', self.marker, file=sys.stderr, flush=True)
    def get_marker(self):
        m, self.marker = self.marker, None
        return m
marker_reader = MarkerReader(fifo_filename) if fifo_filename else None

proc = subprocess.Popen(cmd)
print('pid:', proc.pid)

class Region: pass

def parse_maps(pid):
    regions = []
    for s in open('/proc/%d/maps' % pid):
        s = s.rstrip('\n')
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+) +(.{4}) ([0-9a-f]+) +([0-9a-f:]+) +([0-9]+) *(.*)', s)
        if m:
            from_addr, to_addr, flags, size, _, _, _ = m.groups()
            r = Region()
            r.from_addr = int(from_addr, 16)
            r.to_addr = int(to_addr, 16)
            r.size = int(size, 16)
            regions.append(r)
    total_size = sum(r.size for r in regions)
    return regions, total_size

class SMapsReport: pass

def parse_smaps(pid):
    sm = SMapsReport()
    sm.referenced_size = sm.dirty_size = 0
    for s in open('/proc/%d/smaps' % pid):
        s = s.rstrip('\n')
        if s.startswith('Private_Dirty:'):
            sm.dirty_size += int(s.split()[1])*1024
        elif s.startswith('Referenced:'):
            sm.referenced_size += int(s.split()[1])*1024
    return sm

class PeriodicReport: pass

class StopCapture(Exception): pass

tstart = time.time()
with EventLogFile(output_filename, 'w') as evlogf:
    # first event is metadata dict
    evlogf.write({
        'experiment_name': experiment_name,
        'output_filename': output_filename,
        'period': period,
        'cmd': cmd,
        'page_size': page_size,
        'pid': proc.pid,
        'tstart': time.time(),
    })

    try:
        while proc.poll() is None:
            tnow = time.time()

            regions, total_size = parse_maps(proc.pid)
            sm = parse_smaps(proc.pid)

            with open('/proc/%d/pagemap' % proc.pid, 'rb') as pmf:
                dirty_cnt = 0
                accessed_cnt = 0

                # workaround to uniformly distribute measurement
                # errors due to slow reading of pagemap file
                # TODO: consolidate page regions, reduce number of
                # pagemap file reads
                regions_ = list(regions)
                random.shuffle(regions_)

                for r in regions_:
                    r.pagemap_data = None
                    pmf.seek(r.from_addr//page_size*8)
                    npages = (r.to_addr - r.from_addr)//page_size
                    if npages == 0: continue
                    dlen = npages*8
                    d = pmf.read(dlen)
                    if len(d) == 0: continue
                    if len(d) < dlen: raise StopCapture()
                    a0 = np.frombuffer(d, dtype='uint8')
                    a1 = a0.reshape((npages, 8))[:, 6:]
                    a2 = ((a1[:,0] & 0x80) >> 7) | (a1[:,1] & 0x02)
                    # 0x01 - dirty, 0x02 - accessed
                    dirty_cnt += int((a2 & 0x01).sum())
                    accessed_cnt += int(((a2 & 0x02) >> 1).sum())
                    r.pagemap_data = a2
                    assert len(r.pagemap_data) == npages

                pr = PeriodicReport()
                pr.regions = regions
                pr.t = tnow - tstart
                pr.tread = time.time() - tnow
                pr.total_size = total_size
                pr.dirty_size = dirty_cnt*page_size
                pr.accessed_size = accessed_cnt*page_size
                pr.smap_dirty_size = sm.dirty_size
                pr.smap_accessed_size = sm.referenced_size
                pr.marker = marker_reader.get_marker() if marker_reader else None

                evlogf.write(pr)

                for s in '14':
                    with open('/proc/%d/clear_refs' % proc.pid, 'w') as fclear:
                        fclear.write(s+'\n')

                MB = 1024**2
                print('\npagemap: @ %.1fs Tr:%.3fs S:%.0fM D:%.0fM A:%.0fM smD:%.0fM smA:%.0fM' % (
                    pr.t, pr.tread,
                    pr.total_size/MB,
                    pr.dirty_size/MB, pr.accessed_size/MB,
                    pr.smap_dirty_size/MB, pr.smap_accessed_size/MB),
                    file=sys.stderr, flush=True)

            time.sleep(max(0, tnow + period - time.time()))
    except (PermissionError, StopCapture):
        pass # sub-process have finished
    finally:
        print('VM page flags capture completed.')
        if fifo_filename:
            try: os.unlink(fifo_filename)
            except: pass

