#!/bin/bash

set -eux
export syn=true
export hyp=true
export mer=true

export mdl="syn_hyp_mer"

. scripts/wikitext2/wikitext2_base.sh
