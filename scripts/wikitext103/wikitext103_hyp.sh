#!/bin/bash

set -eux
export hyp=true
export data="wikitext103"
. scripts/run_once.sh
