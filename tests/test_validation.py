from scraper_app.db.models import ScrapingStep, new_id
from scraper_app.workflow.validation import validate_step, validate_steps


def test_valid_step():
    step = ScrapingStep(
        id=new_id(),
        association_id=new_id(),
        position=0,
        action="click",
        phase="record",
        locator_type="button_text",
        locator_value="Phones",
    )
    assert validate_step(step) == []


def test_invalid_action():
    step = ScrapingStep(
        id=new_id(),
        association_id=new_id(),
        position=0,
        action="hack_the_planet",
        phase="discovery",
    )
    errors = validate_step(step)
    assert any("Unknown action" in e for e in errors)


def test_validate_steps_reports_index():
    steps = [
        ScrapingStep(
            id=new_id(),
            association_id="a",
            position=0,
            action="navigate",
            phase="discovery",
        ),
        ScrapingStep(
            id=new_id(),
            association_id="a",
            position=1,
            action="nope",
            phase="discovery",
        ),
    ]
    errors = validate_steps(steps)
    assert any("Step 1" in e for e in errors)
