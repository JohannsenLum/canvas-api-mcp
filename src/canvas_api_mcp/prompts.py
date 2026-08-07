# src/canvas_api_mcp/prompts.py
"""Workflow prompts — the reusable multi-step procedures."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import Field


def build_week_ahead(days: int) -> str:
    return (
        f"Plan my next {days} days of coursework.\n\n"
        f"1. Call whats_due with days={days} to get every deadline and event.\n"
        "2. Call my_courses to map course_id values to course names.\n"
        "3. For anything due whose submission state is unclear, call my_submission "
        "to check whether I have already handed it in.\n"
        "4. Present the result as a table ordered by due date: what, which course, "
        "when it is due, how many days away, and whether it is submitted.\n"
        "5. Flag anything due within 48 hours that is not yet submitted, and anything "
        "where two deadlines fall on the same day.\n"
        "Do not guess at dates — use only values returned by the tools."
    )


def build_study_pack(course: str, topic: str) -> str:
    return (
        f"Build me a study pack on '{topic}' for {course}.\n\n"
        f"1. Call my_courses to resolve {course} to its course_id.\n"
        "2. Call course_content to see the modules and what is in them.\n"
        f"3. Identify the modules and files relevant to '{topic}'. Use list_files with "
        "a search term if the module names are not descriptive enough.\n"
        "4. Call read_file on the most relevant files — prefer lecture slides and notes.\n"
        f"5. Produce a summary of '{topic}' grounded only in that material: the key "
        "definitions, the main results, and any worked examples you found.\n"
        "6. Cite which file each point came from, and say plainly if the material does "
        "not cover something rather than filling the gap from your own knowledge."
    )


def build_grade_check(course: str) -> str:
    return (
        f"Work out where I stand in {course}.\n\n"
        f"1. Call my_courses to resolve {course} to its course_id.\n"
        "2. Call my_grades for that course to get my current score.\n"
        "3. Call list_assignments for the course to get every assignment and its "
        "points_possible, along with what I have submitted.\n"
        "4. Compute how many points remain unearned and unattempted.\n"
        "5. Tell me my current standing, what is still outstanding, and what I would "
        "need on the remaining work to reach the next grade boundary.\n"
        "State your assumptions about weighting explicitly — if the grading scheme is "
        "not visible via the API, say so instead of inventing one."
    )


def register(mcp: FastMCP) -> None:
    @mcp.prompt(description="Plan the coming days of coursework by deadline and urgency.")
    def week_ahead(
        days: int = Field(default=7, description="How many days ahead to plan"),
    ) -> str:
        """Deadline planning workflow."""
        return build_week_ahead(days)

    @mcp.prompt(description="Gather and summarise course material on a topic.")
    def study_pack(
        course: str = Field(description="Course code or name, e.g. CS3230"),
        topic: str = Field(description="Topic to study, e.g. 'amortised analysis'"),
    ) -> str:
        """Study material gathering workflow."""
        return build_study_pack(course, topic)

    @mcp.prompt(description="Compute standing in a course and what remains.")
    def grade_check(
        course: str = Field(description="Course code or name, e.g. CS3230"),
    ) -> str:
        """Grade standing workflow."""
        return build_grade_check(course)
