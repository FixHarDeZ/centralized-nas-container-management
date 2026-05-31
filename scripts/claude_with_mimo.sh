#!/usr/bin/env bash

# This script is used to run the Claude model with MIMO (Multiple Input Multiple Output) support.

export ANTHROPIC_BASE_URL="https://token-plan-sgp.xiaomimimo.com/anthropic"
export ANTHROPIC_API_KEY="tp-s8sz9z051urfzjlpamj2fwjy7k81rh05acqto1hg0ihpjvey"

cd .. && claude --model mimo-v2.5-pro