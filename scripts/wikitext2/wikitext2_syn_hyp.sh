#!/bin/bash

set -eux
export syn=true
export hyp=true
export mdl="syn_hyp"

. scripts/wikitext2/wikitext2_base.sh