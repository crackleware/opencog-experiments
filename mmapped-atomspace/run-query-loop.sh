#!/usr/bin/env sh

time {
    GUILE_LOAD_PATH=$HOME/tmp/opencog/inst/share/guile/site/2.2/opencog:... \
    python -u $(dirname "$0")/vm-page-flags-capture.py \
        --name opencog/benchmark/query-loop \
        --fifo marker.fifo \
        --period 0.1 \
        --output query-loop.vmpf \
        guile -l bio-loop.scm
    sleep 0.1; killall -q guile
    } 2>&1 | tee vm_page_flags_capture.log

