# tests/test_resources_prompts.py
from canvas_api_mcp.prompts import build_grade_check, build_study_pack, build_week_ahead


def test_week_ahead_prompt_names_the_tools_to_use():
    text = build_week_ahead(7)
    assert "whats_due" in text
    assert "7" in text


def test_study_pack_prompt_includes_course_and_topic():
    text = build_study_pack("CS3230", "amortised analysis")
    assert "CS3230" in text
    assert "amortised analysis" in text
    assert "read_file" in text


def test_grade_check_prompt_references_grade_tools():
    text = build_grade_check("CS3230")
    assert "my_grades" in text
    assert "CS3230" in text
