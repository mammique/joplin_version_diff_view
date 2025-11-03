#!/usr/bin/env python3
import json
import sys
import difflib
import os
import re
from datetime import datetime
import curses
import re as re_ansi

# Improbable marker
NEWLINE_MARKER = "___JOPLIN_NEWLINE___"

# Regex to strip ANSI codes
ANSI_ESCAPE = re_ansi.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text):
    return ANSI_ESCAPE.sub('', text)

def recursive_replace(obj):
    if isinstance(obj, dict):
        return {k: recursive_replace(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [recursive_replace(v) for v in obj]
    elif isinstance(obj, str):
        return obj.replace(NEWLINE_MARKER, '\n')
    else:
        return obj

def parse_diff_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('\\\\\\n', NEWLINE_MARKER)

    title_json = None
    body_json = None

    for line in content.splitlines():
        if line.startswith('title_diff:'):
            json_str = line.split(':', 1)[1].strip()
            if json_str.startswith('"') and json_str.endswith('"'):
                json_str = json_str[1:-1]
            json_str = json_str.replace('\\\"', '"')
            try:
                title_json = json.loads(json_str)
                title_json = recursive_replace(title_json)
            except:
                title_json = []
        elif line.startswith('body_diff:'):
            json_str = line.split(':', 1)[1].strip()
            if json_str.startswith('"') and json_str.endswith('"'):
                json_str = json_str[1:-1]
            json_str = json_str.replace('\\\"', '"')
            try:
                body_json = json.loads(json_str)
                body_json = recursive_replace(body_json)
            except:
                body_json = []

    if title_json is None:
        match = re.search(r'title_diff:\s*"([^"]*)"', content, re.DOTALL)
        if match:
            s = match.group(1).replace('\\\"', '"')
            try:
                title_json = json.loads(s)
                title_json = recursive_replace(title_json)
            except:
                title_json = []
        else:
            title_json = []

    if body_json is None:
        match = re.search(r'body_diff:\s*"([^"]*)"', content, re.DOTALL)
        if match:
            s = match.group(1).replace('\\\"', '"')
            try:
                body_json = json.loads(s)
                body_json = recursive_replace(body_json)
            except:
                body_json = []
        else:
            body_json = []

    return title_json or [], body_json or []

def get_updated_time(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('updated_time:'):
                time_str = line.split(':', 1)[1].strip()
                try:
                    return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                except:
                    return datetime.min
    return datetime.min

def find_related_files(item_id, directory='.'):
    files = []
    for filename in os.listdir(directory):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                if f'item_id: {item_id}' in f.read():
                    files.append(filepath)
        except:
            continue
    return files

def apply_patch(text, patches):
    if not patches:
        return text
    result = []
    idx = 0
    for patch in patches:
        start = patch.get('start1', 0)
        diffs = patch.get('diffs', [])
        result.append(text[idx:start])
        idx = start
        for op, data in diffs:
            if op == 0:
                result.append(data)
                idx += len(data)
            elif op == 1:
                result.append(data)
            elif op == -1:
                idx += len(data)
    result.append(text[idx:])
    return ''.join(result)

def parse_note_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    if '\nid:' in content:
        note = content.split('\nid:', 1)[0]
    else:
        note = content
    lines = note.rstrip().splitlines()
    title = lines[0] if lines else ''
    body = '\n'.join(lines[2:]) if len(lines) > 2 and not lines[1].strip() else '\n'.join(lines[1:])
    return title, body

def color_line_ansi(line):
    """Apply ANSI colors (for pre-calculation)"""
    if line.startswith('+') and not line.startswith('+++'):
        return f"\033[32m{line}\033[0m"
    if line.startswith('-') and not line.startswith('---'):
        return f"\033[31m{line}\033[0m"
    if line.startswith('@@'):
        return f"\033[36m{line}\033[0m"
    return line

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # +
    curses.init_pair(2, curses.COLOR_RED, -1)     # -
    curses.init_pair(3, curses.COLOR_CYAN, -1)    # @@

    if len(sys.argv) != 2:
        stdscr.addstr(0, 0, "Usage: python3 joplin_history_diff.py <item_id>")
        stdscr.refresh()
        stdscr.getch()
        return

    item_id = sys.argv[1]
    current_file = f"{item_id}.md"

    if not os.path.exists(current_file):
        stdscr.addstr(0, 0, f"Current file not found: {current_file}")
        stdscr.refresh()
        stdscr.getch()
        return

    related_files = find_related_files(item_id)
    if not related_files:
        stdscr.addstr(0, 0, "No diff files found.")
        stdscr.refresh()
        stdscr.getch()
        return

    related_files.sort(key=get_updated_time)
    current_title, current_body = parse_note_file(current_file)

    # Pre-calculate all versions
    versions = []
    prev_title = ""
    prev_body = ""
    versions.append(("Version 0 (empty)", "", ""))

    for i, diff_file in enumerate(related_files, 1):
        title_patches, body_patches = parse_diff_file(diff_file)
        new_title = apply_patch(prev_title, title_patches)
        new_body = apply_patch(prev_body, body_patches)

        title_diff_lines = []
        body_diff_lines = []
        if new_title != prev_title:
            for line in difflib.unified_diff(prev_title.splitlines(), new_title.splitlines(), lineterm='', n=0):
                if line and not line.startswith(('---', '+++')):
                    title_diff_lines.append(color_line_ansi(line))
        if new_body != prev_body:
            for line in difflib.unified_diff(prev_body.splitlines(), new_body.splitlines(), lineterm='', n=0):
                if line and not line.startswith(('---', '+++')):
                    body_diff_lines.append(color_line_ansi(line))

        versions.append((
            f"Version {i}: {os.path.basename(diff_file)}",
            '\n'.join(title_diff_lines),
            '\n'.join(body_diff_lines)
        ))
        prev_title, prev_body = new_title, new_body

    success = prev_title == current_title and prev_body == current_body

    i = 0
    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        y = 0
        def print_centered(text):
            nonlocal y
            if y >= h - 1: return
            x = max(0, (w - len(text)) // 2)
            stdscr.addstr(y, x, text)
            y += 1

        def print_left(text, color_pair=None):
            nonlocal y
            if y >= h - 1: return
            clean_text = strip_ansi(text)
            if color_pair:
                stdscr.addstr(y, 0, clean_text, color_pair)
            else:
                stdscr.addstr(y, 0, clean_text)
            y += 1

        print_centered("=" * 70)
        print_centered(versions[i][0])
        print_centered("=" * 70)
        y += 1

        if versions[i][1]:
            print_left("TITLE changed:")
            for line in versions[i][1].splitlines():
                clean = strip_ansi(line)
                if line.startswith('\033[32m+'):
                    print_left(clean, curses.color_pair(1))
                elif line.startswith('\033[31m-'):
                    print_left(clean, curses.color_pair(2))
                elif line.startswith('\033[36m@@'):
                    print_left(clean, curses.color_pair(3))
                else:
                    print_left(clean)
            y += 1

        if versions[i][2]:
            print_left("BODY changed:")
            for line in versions[i][2].splitlines():
                clean = strip_ansi(line)
                if line.startswith('\033[32m+'):
                    print_left(clean, curses.color_pair(1))
                elif line.startswith('\033[31m-'):
                    print_left(clean, curses.color_pair(2))
                elif line.startswith('\033[36m@@'):
                    print_left(clean, curses.color_pair(3))
                else:
                    print_left(clean)

        if i == len(versions) - 1:
            y += 1
            print_centered("=" * 70)
            status = "SUCCESS: Final version matches current note" if success else "FAILURE: Divergence detected"
            print_centered(status)
            print_centered("=" * 70)

        y += 1
        nav = f"Version {i}/{len(versions)-1} — Page Down ↓ | Page Up ↑ | q to quit"
        print_centered(nav)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_NPAGE, curses.KEY_DOWN, ord(' '), ord('j')):
            if i < len(versions) - 1:
                i += 1
        elif key in (curses.KEY_PPAGE, curses.KEY_UP, ord('k')):
            if i > 0:
                i -= 1
        elif key in (ord('q'), ord('Q'), 27):
            break

if __name__ == "__main__":
    curses.wrapper(main)
