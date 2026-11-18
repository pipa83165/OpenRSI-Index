#!/bin/bash
set -eu
cd /
exec /usr/local/bin/python -I /tests/evaluate.py
