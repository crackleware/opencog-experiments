##
INTERACTIVE = 'get_ipython' in globals()

import sys
import os
from pprint import pprint as pp
import struct
import pickle
import numpy as np
import zstd

import intervals as I

import matplotlib.style
import matplotlib as mpl
if INTERACTIVE: mpl.use('Qt5Agg')
# mpl.style.use('seaborn-paper') # smaller size
mpl.style.use('dark_background')
from matplotlib import pyplot as plt

from event_log_file import EventLogFile

if INTERACTIVE: input_filename = 'query-loop.vmpf'
else: input_filename = sys.argv[1]

def save_pickled(obj, filename):
    with open(filename, 'wb+') as f: pickle.dump(obj, f)
def load_pickled(filename):
    return pickle.load(open(filename, 'rb'))

def savefig(plt, filename):
    print('saving', filename)
    plt.savefig(filename, dpi=200)

class PeriodicReport: pass
class Region: pass

class ConsolidatedRegion:
    def __init__(self, from_addr, to_addr):
        self.from_addr = from_addr
        self.to_addr = to_addr
    @property
    def key(self):
        return (self.from_addr, self.to_addr)
    @property
    def npages(self):
        return (self.to_addr - self.from_addr) // page_size

print('loading pagemap samples...')

samples = []
with EventLogFile(input_filename, 'r') as evlogf:
    metadata = evlogf.read()
    page_size = metadata['page_size']
    while 1:
        pr = evlogf.read()
        if not pr: break
        samples.append(pr)
print('len(samples):', len(samples))
title_prefix = metadata['experiment_name'] + '\n'
##

PM_DIRTY    = 0x01
PM_ACCESSED = 0x02
def is_dirty(page_flags):
    return page_flags & PM_DIRTY
def is_accessed(page_flags):
    return (page_flags & PM_ACCESSED) >> 1

def iter_samples(progress=False):
    for sidx, s in enumerate(samples):
        if progress and sidx % 10 == 0:
            print('%d/%d    ' % (sidx, len(samples)), end='\r', flush=1)
        yield s

print('consolidating regions...')

rintervals = I.empty()
for s in iter_samples(progress=True):
    for r in s.regions:
        if r.pagemap_data is not None:
            # print('%X -> %X' % (r.from_addr, r.to_addr))
            rintervals |= I.closedopen(r.from_addr, r.to_addr)

print('len(rintervals):', len(rintervals))
#
def get_cons_region_for_addr_range(cons_regions, from_addr, to_addr):
    ' returns: cr, (offset_start, offset_end) '
    for ri, cr in zip(rintervals, cons_regions):
        if I.closedopen(from_addr, to_addr) in ri:
            return cr, (from_addr - ri.lower, to_addr - ri.lower)
    else:
        raise Exception('consolidated region not found')

from collections import OrderedDict
for s in iter_samples(progress=True):
    s.cons_regions = OrderedDict() # {(from_addr, to_addr): ConsolidatedRegion, ...}
    for ri in rintervals:
        cr = ConsolidatedRegion(ri.lower, ri.upper)
        cr.page_flags = np.zeros(cr.npages, dtype='uint8')
        s.cons_regions[cr.key] = cr
    for r in s.regions:
        if r.pagemap_data is not None:
            cr, (offset_start, offset_end) = \
                get_cons_region_for_addr_range(s.cons_regions.values(), r.from_addr, r.to_addr)
            indices = np.arange(offset_start//page_size, offset_end//page_size)
            cr.page_flags[indices] = r.pagemap_data
#
for s in iter_samples():
    del s.regions
#
if INTERACTIVE: save_pickled(samples, 'samples.pickle')
##
if INTERACTIVE: samples = load_pickled('samples.pickle')
##
class AccumulatePageCounts:
    def __init__(self, sidx_start, sidx_end):
        acc_cr_by_addr = {}
        for ri in rintervals:
            cr = ConsolidatedRegion(ri.lower, ri.upper)
            cr.page_dirty_cnt = np.zeros(cr.npages, dtype='uint32')
            cr.page_accessed_cnt = np.zeros(cr.npages, dtype='uint32')
            cr.page_dirty_accessed_cnt = np.zeros(cr.npages, dtype='uint32')
            acc_cr_by_addr[cr.key] = cr

        nknown_pages = sum(cr.npages for cr in acc_cr_by_addr.values())

        for sidx, s in enumerate(iter_samples(progress=True)):
            if sidx_start <= sidx < sidx_end:
                for cr in s.cons_regions.values():
                    acr = acc_cr_by_addr[cr.key]
                    acr.page_dirty_cnt += is_dirty(cr.page_flags)
                    acr.page_accessed_cnt += is_accessed(cr.page_flags)
                    acr.page_dirty_accessed_cnt += is_dirty(cr.page_flags) | is_accessed(cr.page_flags)

        page_dirty_cnt = np.zeros(nknown_pages, dtype='uint32')
        page_accessed_cnt = np.zeros(nknown_pages, dtype='uint32')
        page_dirty_accessed_cnt = np.zeros(nknown_pages, dtype='uint32')
        i = 0
        for cr in acc_cr_by_addr.values():
            page_dirty_cnt         [i:i+cr.npages] += cr.page_dirty_cnt
            page_accessed_cnt      [i:i+cr.npages] += cr.page_accessed_cnt
            page_dirty_accessed_cnt[i:i+cr.npages] += cr.page_dirty_accessed_cnt
            i += cr.npages

        self.__dict__.update(locals())

nknown_pages = AccumulatePageCounts(0, 0).nknown_pages
print('number of known memory pages:', nknown_pages)

#
markers = {}
for s in samples:
    if s.marker:
        markers[s.marker] = s.t
tlast = s.t
print('markers:', markers)
##
plt.figure(figsize=(15,10))
for isubplt, (attr, label) in enumerate([
    ('page_dirty_cnt',          'dirty'),
    ('page_accessed_cnt',       'referenced'),
    ('page_dirty_accessed_cnt', 'dirty & referenced'),
]):
    plt.subplot(3,1,isubplt+1)
    if isubplt == 0: plt.title(title_prefix)
    for stage, (sidx_start, sidx_end) in [
        ('loading',    (0, len(samples))),
        ('processing', (int(len(samples)*markers['triangle-benchmark']/tlast), len(samples))),
    ]:
        apc = AccumulatePageCounts(sidx_start, sidx_end)
        arr = getattr(apc, attr)
        psorted = np.sort(arr)[::-1]
        plt.plot(psorted/(sidx_end-sidx_start)*100, label=stage)
    plt.ylabel(label+' / periods (%)')
    if isubplt == 0: plt.text(len(psorted)*0.05, 90, 'reverse sorted by y-axis')
    if isubplt == 2: plt.xlabel('memory page')
    plt.legend()
plt.tight_layout()
savefig(plt, 'accumulated_page_counts.png')
if INTERACTIVE: plt.show()
plt.close()
##
scaledown = 500
page_accessed = np.zeros((len(samples), nknown_pages//scaledown+1), dtype='uint32')
for sidx, s in enumerate(iter_samples(progress=True)):
    i = 0
    for cr in s.cons_regions.values():
        np.add.at(
            page_accessed[sidx, :],
            np.arange(i, i+cr.npages)//scaledown,
            is_accessed(cr.page_flags) | is_dirty(cr.page_flags))
        i += cr.npages
##
if INTERACTIVE: save_pickled(page_accessed, 'page_accessed.pickle')
##
if INTERACTIVE: page_accessed = load_pickled('page_accessed.pickle')
##
plt.figure(figsize=(15,10))
plt.subplot(2,1,1)
plt.imshow(page_accessed.transpose()/scaledown*100, origin='lower', aspect='auto', cmap=plt.get_cmap('tab20b'))
plt.title(title_prefix+'VM page region heat map')
plt.xlabel('time (s)')
plt.ylabel('page region')
xticks = [(i, '%.0f' % samples[i].t) for i in range(0, len(samples), 100)]
plt.xticks(*zip(*xticks))
nmark = len(markers)
for m, t in markers.items():
    x = len(samples)*t/tlast
    y = page_accessed.shape[1]
    plt.vlines(
        x, 0, y,
        label=m, colors='r', linestyle='dashed')
    plt.text(x, y, m, color='r')
plt.colorbar(label='page region referenced (%)')
plt.subplot(2,1,2)
MB = 1024**2
plt.plot(*zip(*[(s.t, s.accessed_size/MB) for s in samples]), label='referenced size', linewidth=1)
plt.plot(*zip(*[(s.t, s.dirty_size/MB) for s in samples]), label='dirty size', linewidth=1)
plt.xlabel('time (s)')
plt.ylabel('(MB)')
plt.legend()
plt.tight_layout()
savefig(plt, 'page_region_referenced__sample_period.png')
if INTERACTIVE: plt.show()
plt.close()
##
