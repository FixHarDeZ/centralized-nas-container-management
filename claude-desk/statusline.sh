#!/bin/bash
#
# Status line for the desk: model, cwd, git branch, context bar, and the
# 5h / 7d rate-limit rows with a pace projection.
#
# Vendored from the workstation's ~/.claude/statusline-script.sh. Two things
# were dropped rather than carried over: the Jira segment (needs credentials
# and a fetch script that never ship here, and its `stat -f` is macOS-only)
# and an unused `dwidth` helper that was the only caller of perl.
#
# Lives in the image, not in the home volume — a named volume is only seeded
# from the image while it is empty, so a copy under /home/claude would never
# reach an existing deploy. Referenced by path from claude-settings.json.
#
# Bars are $LIMIT_BAR_W cells wide; set STATUSLINE_BAR_W in the compose env to
# retune for the phone without rebuilding the image.

# Read input JSON from stdin
input=$(cat)

# ANSI Color codes using $'...' syntax
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'

# Foreground colors
YELLOW=$'\033[33m'
BLUE=$'\033[34m'
MAGENTA=$'\033[35m'

# Bright colors
BRIGHT_BLACK=$'\033[90m'
BRIGHT_RED=$'\033[91m'
BRIGHT_GREEN=$'\033[92m'
BRIGHT_YELLOW=$'\033[93m'
BRIGHT_CYAN=$'\033[96m'

# Extract values
model=$(echo "$input" | jq -r '.model.display_name')
cwd=$(echo "$input" | jq -r '.workspace.current_dir')
effort=$(echo "$input" | jq -r '.effort.level // empty')

# Get context window information
usage=$(echo "$input" | jq '.context_window.current_usage')
context_size=$(echo "$input" | jq -r '.context_window.context_window_size')

# Autocompact buffer is ~22.5% of context window
BUFFER_PCT=23

# Fixed width (cells) shared by the context, 5h and wk bars so they align.
LIMIT_BAR_W=${STATUSLINE_BAR_W:-36}

# A phone terminal is ~47 columns; the bars plus the "(bud 60%, -18% → 70%)"
# detail need ~79 and a row that wraps is worse than no bar at all. Below the
# threshold the rows drop the bar and the budget breakdown and keep what the
# small screen can actually use: the percentage, where the pace lands, and the
# reset. At the default width the output is unchanged from the workstation
# copy, so re-vendoring stays a clean diff.
COMPACT=0
[ "$LIMIT_BAR_W" -lt 20 ] 2>/dev/null && COMPACT=1

# Calculate context usage percentage and create progress bar
context_section=""
if [ "$usage" != "null" ] && [ "$usage" != "" ]; then
    input_tokens=$(echo "$usage" | jq -r '.input_tokens // 0')
    cache_creation=$(echo "$usage" | jq -r '.cache_creation_input_tokens // 0')
    cache_read=$(echo "$usage" | jq -r '.cache_read_input_tokens // 0')

    # Total current context usage
    current_usage=$((input_tokens + cache_creation + cache_read))

    # Calculate percentage
    if [ "$context_size" != "null" ] && [ "$context_size" -gt 0 ] 2>/dev/null; then
        pct=$((current_usage * 100 / context_size))

        # Clamp percentage to 100
        [ "$pct" -gt 100 ] && pct=100

        # Create progress bar (shares width with the limit bars)
        bar_width=$LIMIT_BAR_W
        filled=$((pct * bar_width / 100))
        buffer_chars=$((BUFFER_PCT * bar_width / 100))
        free_chars=$((bar_width - filled - buffer_chars))

        # Ensure free_chars doesn't go negative
        [ "$free_chars" -lt 0 ] && free_chars=0

        # If filled extends into buffer zone, reduce buffer display
        if [ "$filled" -gt $((bar_width - buffer_chars)) ]; then
            buffer_chars=$((bar_width - filled))
            [ "$buffer_chars" -lt 0 ] && buffer_chars=0
            free_chars=0
        fi

        # Choose color based on usage level
        if [ "$pct" -lt 50 ]; then
            BAR_COLOR="$BRIGHT_GREEN"
        elif [ "$pct" -lt 70 ]; then
            BAR_COLOR="$BRIGHT_YELLOW"
        elif [ "$pct" -lt 85 ]; then
            BAR_COLOR="$YELLOW"
        else
            BAR_COLOR="$BRIGHT_RED"
        fi

        # Override: warn in yellow once absolute token count exceeds 128k,
        # but only when the bar is still green (higher thresholds take precedence).
        if [ "$current_usage" -gt 128000 ] && [ "$BAR_COLOR" = "$BRIGHT_GREEN" ]; then
            BAR_COLOR="$YELLOW"
        fi

        # Build braille-track bar: used (heavy + marker) · free (light) · buffer (dashed)
        bar="${BAR_COLOR}"
        if [ "$filled" -gt 0 ]; then
            for ((i=0; i<filled-1; i++)); do bar="${bar}━"; done
            bar="${bar}╸"
        fi
        bar="${bar}${RESET}${DIM}"
        for ((i=0; i<free_chars; i++)); do bar="${bar}┄"; done
        bar="${bar}${RESET}${BRIGHT_BLACK}"
        for ((i=0; i<buffer_chars; i++)); do bar="${bar}╌"; done
        bar="${bar}${RESET}"

        # Format tokens
        if [ "$current_usage" -ge 1000000 ]; then
            token_display="$(awk "BEGIN {printf \"%.1f\", $current_usage/1000000}")M"
        elif [ "$current_usage" -ge 1000 ]; then
            token_display="$(awk "BEGIN {printf \"%.0f\", $current_usage/1000}")K"
        else
            token_display="$current_usage"
        fi

        # Own row, aligned with the 5h/wk limit rows (label padded to 3)
        [ "$COMPACT" = "1" ] && bar=""
        context_section=$(printf '\n  %sctx%s %s%s%s%%%s %s(%s)%s' \
            "$DIM" "$RESET" "${bar:+$bar }" "$BAR_COLOR" "$pct" "$RESET" "$DIM" "$token_display" "$RESET")
    fi
fi

# Get git branch if in a git repo
git_section=""
if cd "$cwd" 2>/dev/null && git rev-parse --git-dir > /dev/null 2>&1; then
    git_branch=$(git -c core.useBuiltinFSMonitor=false branch --show-current 2>/dev/null)
    if [ -n "$git_branch" ]; then
        # Check for uncommitted changes
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            git_section=" ${DIM}|${RESET} ${MAGENTA}${git_branch}${RESET}${DIM}*${RESET}"
        else
            git_section=" ${DIM}|${RESET} ${MAGENTA}${git_branch}${RESET}"
        fi
    fi
fi

# Window lengths in seconds (for budget/projection math)
W_5H=18000
W_7D=604800

# Budget bar: usage colored by how close it is to the budget marker —
# green < 90% of budget, yellow >= 90%, red >= 100%. ┊ = budget marker.
# When usage reaches/covers the marker cell it stays rendered as a red ┊
# (instead of being overdrawn by the fill).
# Args: $1 used%   $2 budget% (-1 = unknown)   $3 width
make_budget_bar() {
    local pct="$1" bud="$2" w="$3"
    local filled bcell
    filled=$(awk -v p="$pct" -v w="$w" 'BEGIN{f=int(p/100*w+0.5);if(f>w)f=w;if(f<0)f=0;print f}')
    if awk -v b="$bud" 'BEGIN{exit !(b<0)}'; then
        bcell=-1
    else
        bcell=$(awk -v b="$bud" -v w="$w" 'BEGIN{c=int(b/100*w+0.5);if(c>w)c=w;if(c<0)c=0;print c}')
    fi

    # Fill color from usage relative to budget: <90% green, >=90% yellow, >=100% red.
    local fill="$BRIGHT_GREEN"
    if [ "$bcell" -ge 0 ]; then
        if awk -v p="$pct" -v b="$bud" 'BEGIN{exit !(b>0 && p>=b)}'; then fill="$BRIGHT_RED"
        elif awk -v p="$pct" -v b="$bud" 'BEGIN{exit !(b>0 && p>=0.9*b)}'; then fill="$BRIGHT_YELLOW"
        fi
    fi

    local out="" i
    for ((i=0; i<w; i++)); do
        if [ "$bcell" -ge 0 ] && [ "$i" -eq "$bcell" ] && [ "$i" -le "$filled" ]; then
            # Usage reached/covered the budget pixel: keep the marker, red.
            out="${out}${BRIGHT_RED}┊"
        elif [ "$i" -lt "$filled" ]; then
            out="${out}${fill}━"
        elif [ "$i" -eq "$filled" ] && [ "$filled" -lt "$w" ]; then
            out="${out}${fill}╸"
        else
            if [ "$bcell" -ge 0 ] && [ "$i" -eq "$bcell" ]; then out="${out}${BRIGHT_YELLOW}┊"
            else out="${out}${DIM}┄"; fi
        fi
    done
    printf '%s%s' "$out" "$RESET"
}

# Humanize seconds-until-reset -> "2h13m" / "3d" / "12m"
fmt_reset() {
    local secs="$1"
    [ "$secs" -le 0 ] && { printf 'now'; return; }
    local d=$((secs / 86400))
    local h=$(((secs % 86400) / 3600))
    local m=$(((secs % 3600) / 60))
    if [ "$d" -gt 0 ]; then printf '%dd' "$d"
    elif [ "$h" -gt 0 ]; then printf '%dh%dm' "$h" "$m"
    else printf '%dm' "$m"; fi
}

# One limit row (fixed width $LIMIT_BAR_W):
#   "  <label> <budget-bar> <pct>% (bud B%, ±D% → proj%) <verdict>  ↻ <reset>"
# Args: $1 label  $2 used%  $3 reset_at(epoch)  $4 window_secs
limit_row() {
    local label="$1" used_raw="$2" reset_at="$3" window="$4"
    local now pct
    now=$(date +%s)
    pct=$(awk -v u="$used_raw" 'BEGIN{printf "%.0f", u}')

    # Projection: how far this pace lands by reset (can exceed 100%)
    local bud=-1 proj=-1 delta=0 hit=0 wall=-1
    if [ -n "$reset_at" ] && [ "$reset_at" != "null" ]; then
        read bud proj delta hit wall < <(awk -v u="$used_raw" -v r="$reset_at" -v now="$now" -v w="$window" 'BEGIN{
            rem=r-now; el=w-rem;
            if(el<=0||rem<0){print "-1 -1 0 0 -1"; exit}
            bud=el/w*100; proj=u/el*w; if(proj>999)proj=999; d=u-bud;
            hit=(proj>=100)?1:0;
            wall=-1; if(u>0 && hit){ s=(100-u)*el/u; wall=rem-s; if(wall<0)wall=0 }
            printf "%.0f %.0f %.0f %d %.0f", bud, proj, d, hit, wall;
        }')
    fi

    # Reset suffix (compact loses the space before the glyph, not the value)
    local reset_str="" reset_gap="  " glyph_gap=" "
    [ "$COMPACT" = "1" ] && reset_gap=" " && glyph_gap=""
    [ -n "$reset_at" ] && [ "$reset_at" != "null" ] \
        && reset_str="${reset_gap}${DIM}↻${glyph_gap}$(fmt_reset $((reset_at - now)))${RESET}"

    # Color for pct/projection: red = will hit, yellow = close, green = safe
    local pcol="$BRIGHT_GREEN"
    awk -v p="$proj" 'BEGIN{exit !(p>=85 && p<100)}' && pcol="$YELLOW"
    [ "$hit" = "1" ] && pcol="$BRIGHT_RED"

    # Tail (everything right of the bar)
    local tail
    if [ "$bud" = "-1" ]; then
        tail="${pcol}${pct}%${RESET}${DIM} (new window)${RESET}${reset_str}"
    else
        local dstr
        if [ "${delta#-}" = "$delta" ]; then dstr="+${delta}%"; else dstr="${delta}%"; fi
        local verdict
        if [ "$hit" = "1" ]; then
            if [ "$wall" -gt 0 ] 2>/dev/null && [ "$COMPACT" != "1" ]; then
                verdict=" ${BRIGHT_RED}⚠${RESET}${DIM} wall -$(fmt_reset "$wall")${RESET}"
            else
                verdict=" ${BRIGHT_RED}⚠${RESET}"
            fi
        else
            verdict=" ${BRIGHT_GREEN}✓${RESET}"
        fi
        if [ "$COMPACT" = "1" ]; then
            tail="${pcol}${pct}% → ${proj}%${RESET}${verdict}${reset_str}"
        else
            tail="${pcol}${pct}%${RESET}${DIM} (bud ${bud}%, ${dstr} ${RESET}${pcol}→ ${proj}%${RESET}${DIM})${RESET}${verdict}${reset_str}"
        fi
    fi

    # Fixed, equal width for every limit row (aligned block)
    local bar=""
    [ "$COMPACT" = "1" ] || bar="$(make_budget_bar "$pct" "$bud" "$LIMIT_BAR_W") "
    printf '\n  %s%-3s%s %s%s' "$DIM" "$label" "$RESET" "$bar" "$tail"
}

# Effort level section (absent when model doesn't support effort)
effort_section=""
if [ -n "$effort" ]; then
    effort_section=" ${DIM}|${RESET} ${BLUE}${effort}${RESET}"
fi

# Display directory name
dir_name=$(basename "$cwd")

# Line 1 (the context bar is its own row below it)
line1="${BOLD}${BRIGHT_CYAN}${model}${RESET}${effort_section} ${DIM}|${RESET} ${YELLOW}${dir_name}${RESET}${git_section}${context_section}"

# Rate limit rows (Pro/Max only; absent until first API response)
limits_section=""
session_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
if [ -n "$session_pct" ]; then
    session_reset=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
    limits_section="${limits_section}$(limit_row "5h" "$session_pct" "$session_reset" "$W_5H")"
fi
week_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
if [ -n "$week_pct" ]; then
    week_reset=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
    limits_section="${limits_section}$(limit_row "wk" "$week_pct" "$week_reset" "$W_7D")"
fi

# Render
printf '%b\n' "${line1}${limits_section}"
