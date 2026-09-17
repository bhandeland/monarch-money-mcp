#!/usr/bin/env bash
# Clear stale Monarch Money session files to force a fresh login
rm -f "$HOME/.monarchmoney_session" .mm/mm_session.pickle
echo "Monarch Money sessions cleared."
