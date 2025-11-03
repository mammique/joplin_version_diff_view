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
                    dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    return "Unknown"
    return "Unknown"

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

    related_files.sort(key=lambda f: os.path.getmtime(f))
    current_title, current_body = parse_note_file(current_file)

    # Pre-calculate versions
    versions = []
    prev_title = ""
    prev_body = ""
    versions.append(("Version 0 (empty)", "—", [], []))

    for i, diff_file in enumerate(related_files, 1):
        title_patches, body_patches = parse_diff_file(diff_file)
        new_title = apply_patch(prev_title, title_patches)
        new_body = apply_patch(prev_body, body_patches)

        diff_date = get_updated_time(diff_file)

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
            diff_date,
            title_diff_lines,
            body_diff_lines
        ))
        prev_title, prev_body = new_title, new_body

    success = prev_title == current_title and prev_body == current_body
    total_versions = len(versions) - 1
    current_version = 0
    scroll_offset = 0
    number_buffer = ""

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        # Build display lines
        all_lines = []
        version_name, version_date, title_lines, body_lines = versions[current_version]

        all_lines.append(f"{'='*70}")
        all_lines.append(version_name)
        all_lines.append(f"Date: {version_date}")
        all_lines.append(f"{'='*70}")
        all_lines.append("")

        if title_lines:
            all_lines.append("TITLE changed:")
            all_lines.extend(title_lines)
            all_lines.append("")

        if body_lines:
            all_lines.append("BODY changed:")
            all_lines.extend(body_lines)

        if current_version == total_versions:
            all_lines.append("")
            all_lines.append(f"{'='*70}")
            status = "SUCCESS: Final version matches current note" if success else "FAILURE: Divergence detected"
            all_lines.append(status)
            all_lines.append(f"{'='*70}")

        # Scroll
        visible_lines = all_lines[scroll_offset:scroll_offset + h - 2]
        max_scroll = max(0, len(all_lines) - (h - 2))

        y = 0
        for line in visible_lines:
            if y >= h - 2:
                break
            clean = strip_ansi(line)
            if line.startswith('\033[32m+'):
                stdscr.addstr(y, 0, clean, curses.color_pair(1))
            elif line.startswith('\033[31m-'):
                stdscr.addstr(y, 0, clean, curses.color_pair(2))
            elif line.startswith('\033[36m@@'):
                stdscr.addstr(y, 0, clean, curses.color_pair(3))
            else:
                stdscr.addstr(y, 0, clean)
            y += 1

        # Status bar
        nav = f"Version {current_version}/{total_versions} | Scroll: {scroll_offset}/{max_scroll} | "
        nav += "PgUp/PgDn: version | ↑↓: scroll | Home/End | [0-{total_versions}]+Enter | q:quit"
        if number_buffer:
            nav += f" → Go to: {number_buffer}_"
        stdscr.addstr(h-1, 0, nav[:w-1])

        stdscr.refresh()

        key = stdscr.getch()

        # Number input
        if ord('0') <= key <= ord('9'):
            number_buffer += chr(key)
            continue
        elif key == 10:  # Enter
            if number_buffer:
                try:
                    target = int(number_buffer)
                    if 0 <= target <= total_versions:
                        current_version = target
                        scroll_offset = 0
                except:
                    pass
                number_buffer = ""
            continue
        elif key in (127, curses.KEY_BACKSPACE):
            number_buffer = number_buffer[:-1]
            continue

        number_buffer = ""

        # Version navigation
        if key == curses.KEY_NPAGE:  # Page Down
            if current_version < total_versions:
                current_version += 1
                scroll_offset = 0
        elif key == curses.KEY_PPAGE:  # Page Up
            if current_version > 0:
                current_version -= 1
                scroll_offset = 0
        elif key == curses.KEY_HOME:
            current_version = 0
            scroll_offset = 0
        elif key == curses.KEY_END:
            current_version = total_versions
            scroll_offset = 0

        # Scroll
        elif key == curses.KEY_UP:
            if scroll_offset > 0:
                scroll_offset -= 1
        elif key == curses.KEY_DOWN:
            if scroll_offset < max_scroll:
                scroll_offset += 1

        elif key in (ord('q'), ord('Q'), 27):
            break

if __name__ == "__main__":
    curses.wrapper(main)
