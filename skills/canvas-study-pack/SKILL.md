---
name: canvas-study-pack
description: Gathers and summarises Canvas LMS course material on a specific topic, grounding every point in the actual course files and citing sources. Use when a student asks to study, review, summarise, or "make a study pack/guide" for a topic, wants notes pulled from course content/readings/files, or asks what a course covers on a subject.
---

# Canvas Study Pack

Read-only research and summarisation skill. Never modify, submit, or post anything —
only report what the canvas-api-mcp tools return.

## Prerequisites

The `canvas-api-mcp` MCP server must be installed and connected in the current client.
If tool calls to `my_courses`, `course_content`, `list_files`, or `read_file` are not
available, tell the user to install it first:
https://mcp.johannsenlum.com/canvas-lms/install

## Procedure

1. **Identify the course.** Call `my_courses` to find the course the topic belongs to.
   If the student named the course, match it; if ambiguous or unstated, ask which course
   or check the most likely candidates via step 2 before guessing.

2. **Survey course content.** Call `course_content` for the identified course to see
   what modules/content exist and to help locate material related to the topic.

3. **Search for files on the topic.** Call `list_files` with a search term derived from
   the topic (and course_content findings) to locate candidate files.

4. **Read the most relevant file(s).** Call `read_file` on the file(s) that best match
   the topic based on filename/context from step 3. Read more than one file if several
   are plausibly relevant — do not settle for a single weak match if better candidates
   exist in the list.

5. **Summarise, grounded only in what was read:**
   - Every point in the summary must be traceable to specific content pulled via
     `read_file` in this session.
   - Cite which file each point came from (e.g. "(from `lecture-05-notes.pdf`)") so the
     student can verify.
   - Do NOT supplement with general knowledge about the topic, even if you "know" more
     about it. If the retrieved material is thin, the summary should be thin.
   - If the material available (via `list_files`/`course_content`) does not cover some
     aspect of the topic the student asked about, say so explicitly — e.g. "The course
     files found don't cover X" — instead of filling the gap from general knowledge.

6. If no relevant files are found at all, say plainly that no matching course material
   was found for the topic, and suggest the student try a different search term or
   confirm the course — do not produce a summary from outside knowledge instead.

## Rules

- Ground every claim in retrieved file content; never substitute general/background
  knowledge for material the course doesn't actually contain.
- Always name the source file for each point.
- Explicitly flag topic gaps rather than silently completing them.
- Do not call any write tool. This skill is strictly read-only.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `my_courses` | Identify/confirm the target course |
| `course_content` | Survey modules/content structure for the course |
| `list_files` | Search course files by term |
| `read_file` | Read the content of a specific file to summarise from |
