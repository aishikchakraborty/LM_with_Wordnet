#!/bin/bash

set -eux
export syn=true
export hyp=true
export mer=true
export data="wikitext103"
. scripts/run_once.sh
