#!/bin/bash

set -eux
export syn=true
export data="glove"
export mdl="retro"
. scripts/run_once.sh
